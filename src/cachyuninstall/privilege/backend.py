"""Transaction backend abstraction for the privileged helper.

The helper core (validation, authorization, staleness checks) is backend-
agnostic and tested against FakeBackend. The real implementation,
AlpmBackend, is a thin, defensive adapter over pyalpm's verified API:
  init_transaction(kwargs...) / remove_pkg / prepare / commit / interrupt /
  release, with eventcb/questioncb/progresscb/logcb bridged to typed events.

Nothing here executes shell commands. All removal flows through libalpm.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from cachyuninstall.core.errors import (
    DatabaseUnavailable,
    PackageManagerBusy,
    PackageNotFound,
    TransactionFailed,
)
from cachyuninstall.core.models import PackageName

LOCK_ERRNO = 10  # pm_errno for "unable to lock database" (verified via probe)


def _is_lock_error(exc: BaseException) -> bool:
    """True when a pyalpm error means 'database is locked'.

    Probe-verified: pyalpm.error does NOT expose a usable `.errno` attribute
    (it is missing/None); the pm_errno only appears in the message text, e.g.
    ``transaction could not be initialized, pm_errno 10 (unable to lock
    database)``. So match the message instead of relying on an attribute.
    """
    if getattr(exc, "errno", None) == LOCK_ERRNO:
        return True
    text = str(exc).lower()
    return "pm_errno 10" in text or "unable to lock database" in text


@dataclass(frozen=True, slots=True)
class TxEvent:
    """UI-consumable progress event."""

    kind: str  # "stage" | "progress" | "log" | "question"
    message: str
    target: str = ""
    current: int = 0
    total: int = 0
    percent: int = -1  # -1 = unknown


class EventSink(Protocol):
    def emit(self, event: TxEvent) -> None: ...


class TransactionBackend(Protocol):
    """What the helper needs from a package-transaction engine."""

    def generation(self) -> int: ...
    def is_installed(self, name: PackageName) -> bool: ...
    def remove(self, names: tuple[PackageName, ...], sink: EventSink) -> list[PackageName]: ...
    def request_interrupt(self) -> None: ...


class AlpmBackend:
    """Real backend over pyalpm. Instantiated and used on ONE thread."""

    def __init__(self, root: str = "/", dbpath: str = "/var/lib/pacman/") -> None:
        self._root = root
        self._dbpath = dbpath
        self._handle: Any | None = None
        self._handle_generation: int = -1
        self._transaction: Any | None = None
        self._interrupt = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def _ensure_handle(self) -> Any:
        """Return a handle that reflects the *current* local database.

        libalpm caches the pkgcache inside the handle, so a long-lived handle
        goes blind to changes made by other tools (pacman installs/removes)
        after it was created — that produced false "not installed" answers.
        We therefore key the cached handle to the local-db mtime and recreate
        it whenever the database changed (or after each transaction).
        """
        gen = self.generation()
        if self._handle is not None and gen == self._handle_generation:
            return self._handle
        import pyalpm

        try:
            self._handle = pyalpm.Handle(self._root, self._dbpath)
        except Exception as exc:
            raise DatabaseUnavailable("Cannot open package database", detail=str(exc)) from exc
        self._handle_generation = gen
        return self._handle

    def _drop_handle(self) -> None:
        """Release the handle so the next call re-reads the database."""
        self._handle = None
        self._handle_generation = -1

    def generation(self) -> int:
        local_dir = os.path.join(self._dbpath, "local")
        try:
            return os.stat(local_dir).st_mtime_ns
        except OSError as exc:
            raise DatabaseUnavailable("Local database unreadable", detail=str(exc)) from exc

    def is_installed(self, name: PackageName) -> bool:
        handle = self._ensure_handle()
        try:
            return handle.get_localdb().get_pkg(str(name)) is not None
        except Exception:
            return False

    # --------------------------------------------------------------- removal
    def remove(self, names: tuple[PackageName, ...], sink: EventSink) -> list[PackageName]:
        import pyalpm

        handle = self._ensure_handle()
        localdb = handle.get_localdb()
        pkgs: list[Any] = []
        missing: list[str] = []
        for name in names:
            pkg = localdb.get_pkg(str(name))
            if pkg is None:
                missing.append(str(name))
            else:
                pkgs.append(pkg)
        if missing:
            raise PackageNotFound("Package(s) no longer installed: " + ", ".join(missing))
        if not pkgs:
            raise PackageNotFound("Nothing to remove")
        # Capture names NOW: after commit/release libalpm frees the pkgcache
        # and reading pkg.name on stale objects yields garbage/None.
        removed_names = [PackageName(str(p.name)) for p in pkgs]

        # Error-level logs observed during the transaction. Physical QA found
        # that commit() can return successfully while unlink()ing every file
        # (e.g. under a read-only /usr): the DB entry disappears, the files
        # stay, and no exception is raised. Never report that as success.
        errors: list[str] = []

        self._wire_callbacks(handle, pyalpm, sink, errors)
        try:
            transaction = handle.init_transaction()
        except pyalpm.error as exc:
            if _is_lock_error(exc):
                raise PackageManagerBusy("Another package operation is running (database locked).") from exc
            raise TransactionFailed("Could not start the transaction", detail=str(exc)) from exc

        self._transaction = transaction
        self._interrupt.clear()
        try:
            for pkg in pkgs:
                transaction.remove_pkg(pkg)
            sink.emit(TxEvent(kind="stage", message="Preparing transaction…"))
            transaction.prepare()
            sink.emit(TxEvent(kind="stage", message="Committing transaction…"))
            transaction.commit()
            if errors:
                detail = errors[0].strip()
                if len(errors) > 1:
                    detail += f" (+{len(errors) - 1} more libalpm error(s))"
                raise TransactionFailed("libalpm reported errors during removal", detail=detail)
        except pyalpm.error as exc:
            if self._interrupt.is_set():
                raise TransactionFailed("Cancelled during transaction", detail=str(exc)) from exc
            if _is_lock_error(exc):
                raise PackageManagerBusy("Database lock lost/contended.") from exc
            raise TransactionFailed("Package transaction failed", detail=str(exc)) from exc
        finally:
            try:
                transaction.release()
            except Exception:
                pass
            self._transaction = None
            # The transaction rewrote the local DB: drop the handle so any
            # later call observes the new state (never serve a stale pkgcache).
            self._drop_handle()
        return removed_names

    def request_interrupt(self) -> None:
        """Best-effort cooperative stop (D5: never promised as rollback)."""
        self._interrupt.set()
        t = self._transaction
        if t is not None:
            try:
                t.interrupt()
            except Exception:
                pass

    # -------------------------------------------------------------- callbacks
    def _wire_callbacks(
        self,
        handle: Any,
        pyalpm: Any,
        sink: EventSink,
        errors: list[str] | None = None,
    ) -> None:
        def on_event(event_name: Any, *args: Any) -> None:
            # pyalpm eventcb signature: (event_code:int, pkg|None)
            target = ""
            if len(args) > 0 and args[0] is not None:
                target = str(getattr(args[0], "name", ""))
            sink.emit(TxEvent(kind="stage", message=str(event_name), target=target))

        def on_progress(target_name: Any, percent: Any, n: Any, current: Any) -> None:
            sink.emit(
                TxEvent(
                    kind="progress",
                    message=str(target_name),
                    target=str(target_name),
                    current=int(current),
                    total=int(n),
                    percent=int(percent),
                )
            )

        def on_question(question: Any) -> None:
            # Default-deny interactive questions: removal must not need them.
            # Setting answer to False declines conflicts/replacement prompts.
            try:
                question.answer = 0
            except Exception:
                pass
            sink.emit(TxEvent(kind="question", message=str(getattr(question, "text", "question"))))

        def on_log(level: int, msg: Any) -> None:
            text = str(msg).rstrip("\n")[:500]
            if errors is not None:
                try:
                    if int(level) == 1:  # ALPM_LOG_ERROR — never ignore these
                        errors.append(text)
                except (TypeError, ValueError):
                    pass
            sink.emit(TxEvent(kind="log", message=text))

        handle.eventcb = on_event
        handle.progresscb = on_progress
        handle.questioncb = on_question
        handle.logcb = on_log

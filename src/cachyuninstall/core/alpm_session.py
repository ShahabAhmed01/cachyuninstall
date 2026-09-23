"""Read-side adapter over pyalpm/libalpm.

Responsibilities:
  * create/own the pyalpm Handle lifecycle (one per session object);
  * convert pyalpm Package objects into immutable PackageRecord values;
  * answer ownership lookups from the local file database;
  * expose a monotonic "generation" marker so plans can be rejected when the
    system changed after they were approved.

The module never writes. Transactions live exclusively in privilege/helper.py.
pyalpm objects must not escape this module (they are `Any`-typed C-extension
objects); everything leaving here is a plain dataclass/tuple/str/int.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from cachyuninstall.core.errors import DatabaseUnavailable
from cachyuninstall.core.models import (
    InstallReason,
    Origin,
    PackageName,
    PackageRecord,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

DEFAULT_ROOT = "/"
DEFAULT_DBPATH = "/var/lib/pacman/"

LOG = logging.getLogger("cachyuninstall.alpm")

# Repositories treated as first-party. Anything else configured is OTHER_REPO,
# and 'local' (no sync db match) is FOREIGN.
_OFFICIAL_REPOS = frozenset(
    {"core", "extra", "multilib", "core-testing", "extra-testing", "multilib-testing"}
)


class _Db(Protocol):
    name: str
    pkgcache: Any


class HandleLike(Protocol):
    """The slice of pyalpm.Handle this module relies on (recon-verified)."""

    def get_localdb(self) -> _Db: ...
    def register_syncdb(self, name: str, flags: int) -> _Db: ...
    def get_syncdbs(self) -> Any: ...


HandleFactory = Callable[[str, str], Any]


def _default_handle_factory(root: str, dbpath: str) -> Any:
    import pyalpm  # local import: keeps module importable without pyalpm (tests)

    return pyalpm.Handle(root, dbpath)


class AlpmSession:
    """Thread-affine read session over the local + configured sync DBs.

    pyalpm handles are not thread-safe, so a session object must stay on the
    thread that created it; use one session per worker.
    """

    def __init__(
        self,
        root: str = DEFAULT_ROOT,
        dbpath: str = DEFAULT_DBPATH,
        *,
        handle_factory: HandleFactory | None = None,
    ) -> None:
        self._root = root
        self._dbpath = dbpath
        self._factory: HandleFactory = handle_factory or _default_handle_factory
        self._handle: Any | None = None
        self._sync_names: tuple[str, ...] = ()
        self._owner: int = threading.get_ident()

    # ------------------------------------------------------------------ setup
    def open(self) -> None:
        if self._handle is not None:
            return
        try:
            self._handle = self._factory(self._root, self._dbpath)
        except Exception as exc:  # pyalpm raises pyalpm.error / OSError
            raise DatabaseUnavailable("The package database could not be opened.", detail=str(exc)) from exc
        self._discover_sync_names()

    def _discover_sync_names(self) -> None:
        # pyalpm requires knowing repo names to register them; read pacman.conf
        # repositories from the handle when available, else parse config.
        if self._handle is None:
            raise RuntimeError("session not open")
        names: list[str] = []
        try:
            names = [db.name for db in self._handle.get_syncdbs()]
        except Exception:
            names = []
        if not names:
            names = _repo_names_from_pacman_conf()
        self._sync_names = tuple(dict.fromkeys(names))

    @contextmanager
    def _guard(self) -> Iterator[Any]:
        if threading.get_ident() != self._owner:
            raise RuntimeError("AlpmSession used from a foreign thread")
        if self._handle is None:
            self.open()
        yield self._handle

    # ------------------------------------------------------------- generation
    def generation(self) -> int:
        """Monotonic-ish marker of the local DB. Changing it invalidates plans."""
        local_dir = os.path.join(self._dbpath, "local")
        try:
            return os.stat(local_dir).st_mtime_ns
        except OSError as exc:
            raise DatabaseUnavailable("The local package database is not readable.", detail=str(exc)) from exc

    # -------------------------------------------------------------- packages
    def packages(
        self, *, with_origin_resolution: bool = True, full_detail: bool = True
    ) -> list[PackageRecord]:
        """Enumerate installed packages.

        with_origin_resolution=False skips sync-db probing (fast; origin shown
        as UNKNOWN until enrichment) — used for the two-phase startup (§145).
        full_detail=False additionally skips file lists and reverse-dep
        computation (the two expensive per-package attributes; measured: the
        dominant cost of enumeration), so the UI can paint quickly and enrich
        in the background. Anything needing deps/files must use full detail.
        """
        with self._guard() as handle:
            # Repo priority mirrors pacman's own resolution: first (listed)
            # sync db that provides a package is its origin. CachyOS overlay
            # repos (cachyos-v3 etc.) precede core/extra on CachyOS, which is
            # exactly where those builds are served from.
            repo_names: dict[str, str] = {}
            if with_origin_resolution:
                for dbname in self._sync_names:
                    try:
                        db = handle.register_syncdb(dbname, _sync_flags())
                    except Exception as exc:
                        # An unconfigured/unavailable sync db must not kill reads,
                        # but only trusted pyalpm-style failures are skipped.
                        LOG.debug("sync db %s unavailable: %s", dbname, exc)
                        continue
                    for pkg in db.pkgcache:
                        repo_names.setdefault(pkg.name, dbname)
            out: list[PackageRecord] = []
            try:
                local = handle.get_localdb()
                local_pkgs = list(local.pkgcache)
            except Exception as exc:
                raise DatabaseUnavailable(
                    "The local package database could not be read.", detail=str(exc)
                ) from exc
            for pkg in local_pkgs:
                try:
                    out.append(
                        self._to_record(
                            pkg,
                            repo_names,
                            unknown_when_unmatched=not with_origin_resolution,
                            detail=full_detail,
                        )
                    )
                except Exception:
                    # A single corrupt entry must not kill enumeration (§80):
                    # record the package with minimal data instead of dropping it.
                    out.append(self._fallback_record(pkg))
            return out

    def package(self, name: str) -> PackageRecord | None:
        needle = name
        for rec in self.packages():
            if rec.name == needle:
                return rec
        return None

    def orphans(self) -> list[PackageRecord]:
        return [p for p in self.packages() if p.is_orphan_hint]

    # -------------------------------------------------------------- ownership
    def file_owners(self, absolute_path: str) -> tuple[PackageName, ...]:
        """Names of installed packages owning `absolute_path` (leading '/' ok)."""
        rel = absolute_path.lstrip("/")
        with self._guard() as handle:
            local = handle.get_localdb()
            owners: list[str] = []
            for pkg in local.pkgcache:
                # pkg.files is a list of (path, size, mode) tuples.
                for entry in pkg.files:
                    if entry[0] == rel:
                        owners.append(pkg.name)
                        break
            return tuple(PackageName(o) for o in sorted(owners))

    def refresh_owner_index(self) -> dict[str, tuple[str, ...]]:
        """Whole-DB file->packages index (used by the ownership oracle)."""
        index: dict[str, list[str]] = {}
        with self._guard() as handle:
            local = handle.get_localdb()
            for pkg in local.pkgcache:
                for entry in pkg.files:
                    index.setdefault(entry[0], []).append(pkg.name)
        return {k: tuple(sorted(v)) for k, v in index.items()}

    # ---------------------------------------------------------------- mapping
    @staticmethod
    def _classify(sync_name: str | None) -> tuple[Origin, str]:
        """Classify an installed package by which sync db also provides it.

        A package present only in the local db (sync_name is None) is FOREIGN —
        *not* automatically AUR (it may be a local build, a removed repo, etc.).
        """
        if sync_name is None:
            return Origin.FOREIGN, ""
        if sync_name in _OFFICIAL_REPOS:
            return Origin.OFFICIAL, sync_name
        if sync_name.startswith("cachyos"):
            return Origin.CACHYOS, sync_name
        return Origin.OTHER_REPO, sync_name

    @staticmethod
    def _to_record(
        pkg: Any,
        repo_of: dict[str, str],
        unknown_when_unmatched: bool = False,
        detail: bool = True,
    ) -> PackageRecord:
        sync_name = repo_of.get(pkg.name)
        if sync_name is None and unknown_when_unmatched:
            origin, repo = Origin.UNKNOWN, ""
        else:
            origin, repo = AlpmSession._classify(sync_name)
        if detail:
            files = tuple(f[0] for f in pkg.files)
            backup = tuple(b[0] for b in pkg.backup)
            required_by = tuple(pkg.compute_requiredby())
            optional_for = tuple(pkg.compute_optionalfor())
        else:
            files = ()
            backup = ()
            required_by = ()
            optional_for = ()
        return PackageRecord(
            name=PackageName(pkg.name),
            version=pkg.version,
            arch=pkg.arch,
            description=pkg.desc or "",
            origin=origin,
            repository=repo,
            size_bytes=int(pkg.isize),
            install_date=int(pkg.installdate),
            reason=InstallReason.EXPLICIT if pkg.reason == 0 else InstallReason.DEPENDENCY,
            groups=tuple(pkg.groups),
            depends=tuple(pkg.depends),
            provides=tuple(pkg.provides),
            optdepends=tuple(pkg.optdepends),
            required_by=tuple(PackageName(r) for r in required_by),
            optional_for=tuple(PackageName(o) for o in optional_for),
            files=files,
            backup_files=backup,
            licenses=tuple(pkg.licenses),
            url=pkg.url or "",
        )

    @staticmethod
    def _fallback_record(pkg: Any) -> PackageRecord:
        name = PackageName(getattr(pkg, "name", "unknown"))
        version = getattr(pkg, "version", "")
        return PackageRecord(
            name=name,
            version=str(version),
            arch="",
            description="(metadata unavailable — package database entry is inconsistent)",
            origin=Origin.UNKNOWN,
            repository="",
            size_bytes=0,
            install_date=0,
            reason=InstallReason.EXPLICIT,
            groups=(),
            depends=(),
            provides=(),
            optdepends=(),
            required_by=(),
            optional_for=(),
            files=(),
            backup_files=(),
            licenses=(),
            url="",
        )


def _sync_flags() -> int:
    try:
        import pyalpm

        return int(pyalpm.SIG_DATABASE_OPTIONAL)
    except ImportError:
        # Test fakes ignore flags entirely; 0 is a harmless placeholder.
        return 0


def _repo_names_from_pacman_conf(path: str = "/etc/pacman.conf") -> list[str]:
    names: list[str] = []
    try:
        for raw_line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                name = stripped[1:-1]
                if name.lower() != "options":
                    names.append(name)
    except OSError:
        pass
    return names

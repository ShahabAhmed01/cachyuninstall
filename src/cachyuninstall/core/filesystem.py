"""Cleanup execution for user-owned leftovers (unprivileged by design, D2).

Every deletion path goes through paths.py policy + identity re-verification:
the object deleted is proven to be the same object (dev+ino) the user approved
in the preview. Anything unexpected aborts *that item* safely; other items
continue; the result is an honest success/partial report.

Quarantine: when enabled, items are moved (same-filesystem rename via dirfd,
never copy-follow) into ~/.local/share/cachyuninstall/quarantine/<txn>/,
with a JSON manifest for restore.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cachyuninstall.core.errors import FileChanged, PathProtected, PermissionDeniedFs
from cachyuninstall.core.models import Confidence, LeftoverCandidate, ResultKind
from cachyuninstall.core.paths import (
    FileIdentity,
    PathPolicy,
    delete_tree_fd,
    open_parent_nofollow,
)

QUARANTINE_BASE = Path("~/.local/share/cachyuninstall/quarantine")


@dataclass(slots=True)
class ItemResult:
    path: Path
    ok: bool
    freed_bytes: int = 0
    error: str = ""
    quarantined: bool = False


@dataclass(slots=True)
class CleanupReport:
    kind: ResultKind
    items: list[ItemResult] = field(default_factory=list)

    @property
    def freed_bytes(self) -> int:
        return sum(i.freed_bytes for i in self.items)


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    original_path: str
    quarantine_path: str
    moved_at: int
    size_bytes: int
    dev: int
    ino: int


class Quarantine:
    """Manifest-managed holding area for user-owned cleanup items."""

    def __init__(self, base: Path | None = None) -> None:
        self.base = (base or QUARANTINE_BASE).expanduser()

    def _manifest_path(self, txn: str) -> Path:
        return self.base / txn / "manifest.json"

    def store(
        self,
        txn: str,
        identity: FileIdentity,
        measured_size: int,
    ) -> Path:
        """Move `identity.path` into quarantine via dirfd rename (no traversal)."""
        dest_dir = self.base / txn / "items"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"{identity.path.name}.{identity.ino:x}"
        dest = dest_dir / dest_name
        src_fd, src_name = open_parent_nofollow(identity.path)
        try:
            from cachyuninstall.core.paths import verify_identity

            verify_identity(src_fd, src_name, identity)
            dst_fd = os.open(dest_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.rename(src_name, dest_name, src_dir_fd=src_fd, dst_dir_fd=dst_fd)
            finally:
                os.close(dst_fd)
        finally:
            os.close(src_fd)
        entry = QuarantineEntry(
            original_path=str(identity.path),
            quarantine_path=str(dest),
            moved_at=int(time.time()),
            size_bytes=measured_size,
            dev=identity.dev,
            ino=identity.ino,
        )
        self._append_manifest(txn, entry)
        return dest

    def _append_manifest(self, txn: str, entry: QuarantineEntry) -> None:
        manifest = self._manifest_path(txn)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, object]] = []
        if manifest.exists():
            try:
                entries = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                entries = []
        entries.append(asdict(entry))
        tmp = manifest.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        os.replace(tmp, manifest)

    def list_entries(self) -> list[QuarantineEntry]:
        out: list[QuarantineEntry] = []
        if not self.base.exists():
            return out
        for manifest in self.base.glob("*/manifest.json"):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for raw in data:
                out.append(QuarantineEntry(**raw))
        return out

    def restore(self, entry: QuarantineEntry, policy: PathPolicy) -> None:
        """Restore one entry; refuses collisions and policy violations."""
        dest = Path(entry.original_path)
        policy.require_allowed(dest)
        if os.path.lexists(dest):
            raise FileChanged(f"Restore target already exists: {dest}")
        src = Path(entry.quarantine_path)
        st = os.lstat(src)
        if (st.st_dev, st.st_ino) != (entry.dev, entry.ino):
            raise FileChanged(f"Quarantined object changed: {src}")
        os.rename(src, dest)

    def total_size(self) -> int:
        total = 0
        for e in self.list_entries():
            total += e.size_bytes
        return total


class CleanupExecutor:
    """Executes approved leftover cleanup, item by item, fail-safe."""

    def __init__(self, policy: PathPolicy, quarantine: Quarantine | None = None) -> None:
        self._policy = policy
        self._quarantine = quarantine

    def execute(self, candidates: list[LeftoverCandidate]) -> CleanupReport:
        report = CleanupReport(kind=ResultKind.SUCCESS)
        txn = uuid.uuid4().hex
        for cand in candidates:
            if cand.confidence is Confidence.PROTECTED:
                report.items.append(ItemResult(path=cand.path, ok=False, error="protected"))
                continue
            try:
                self._execute_one(cand, report, txn)
            except PermissionError as exc:
                report.items.append(ItemResult(path=cand.path, ok=False, error=str(exc)))
            except (FileChanged, PathProtected, PermissionDeniedFs) as exc:
                report.items.append(ItemResult(path=cand.path, ok=False, error=str(exc)))
            except OSError as exc:
                report.items.append(ItemResult(path=cand.path, ok=False, error=str(exc)))
        ok = [i for i in report.items if i.ok]
        failed = [i for i in report.items if not i.ok and i.error != "protected"]
        if failed:
            report.kind = ResultKind.PARTIAL if ok else ResultKind.FAILED
        return report

    def _execute_one(self, cand: LeftoverCandidate, report: CleanupReport, txn: str) -> None:
        self._policy.require_allowed(cand.path)
        identity = FileIdentity.capture(cand.path)
        if self._quarantine is not None:
            dest = self._quarantine.store(txn, identity, cand.size_bytes)
            report.items.append(
                ItemResult(
                    path=cand.path,
                    ok=True,
                    freed_bytes=cand.size_bytes,
                    quarantined=True,
                    error=f"quarantined→{dest}",
                )
            )
            return
        parent_fd, name = open_parent_nofollow(cand.path)
        try:
            freed, _deleted = delete_tree_fd(parent_fd, name, identity)
        finally:
            os.close(parent_fd)
        report.items.append(ItemResult(path=cand.path, ok=True, freed_bytes=freed))

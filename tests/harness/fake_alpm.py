"""Fake libalpm harness — pure Python, no root, no real DB (§125).

Two layers:
  * record factories → real domain PackageRecords (planner/scanner tests);
  * FakeHandle/FakeDb/FakePackage → mimic the *verified* pyalpm surface used
    by AlpmSession (pkgcache/files/reason/compute_*, get_localdb, register_syncdb),
    so session mapping tests cover the same code path as production.

Builders create the named test worlds from the spec (§126).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from cachyuninstall.core.models import (
    InstallReason,
    Origin,
    PackageName,
    PackageRecord,
)

_ctr = itertools.count(1700000000)


def make_record(
    name: str,
    *,
    version: str = "1.0-1",
    reason: InstallReason = InstallReason.EXPLICIT,
    origin: Origin = Origin.OFFICIAL,
    repository: str = "extra",
    depends: tuple[str, ...] = (),
    provides: tuple[str, ...] = (),
    optdepends: tuple[str, ...] = (),
    required_by: tuple[str, ...] = (),
    optional_for: tuple[str, ...] = (),
    files: tuple[str, ...] = (),
    backup_files: tuple[str, ...] = (),
    size: int = 1000,
    description: str = "",
    install_date: int = 1700000000,
) -> PackageRecord:
    return PackageRecord(
        name=PackageName(name),
        version=version,
        arch="x86_64",
        description=description or f"{name} test package",
        origin=origin,
        repository=repository,
        size_bytes=size,
        install_date=install_date,
        reason=reason,
        groups=(),
        depends=depends,
        provides=provides,
        optdepends=optdepends,
        required_by=required_by,
        optional_for=optional_for,
        files=files,
        backup_files=backup_files,
        licenses=("GPL-3.0-or-later",),
        url="",
    )


# ------------------------------------------------------------- package worlds


def world_single() -> list[PackageRecord]:
    """World A: one independent explicit package."""
    return [make_record("solo", files=("usr/bin/solo",))]


def world_shared_dep() -> list[PackageRecord]:
    """World B: A depends on S, B depends on S — S is shared."""
    return [
        make_record("app-a", depends=("shared-lib",)),
        make_record("app-b", depends=("shared-lib",)),
        make_record("shared-lib", reason=InstallReason.DEPENDENCY, required_by=("app-a", "app-b")),
    ]


def world_orphan_chain() -> list[PackageRecord]:
    """World C: app -> mid -> leaf; removing app orphans the chain."""
    return [
        make_record("app-c", depends=("mid",)),
        make_record("mid", reason=InstallReason.DEPENDENCY, depends=("leaf",), required_by=("app-c",)),
        make_record("leaf", reason=InstallReason.DEPENDENCY, required_by=("mid",)),
    ]


def world_blocked() -> list[PackageRecord]:
    """World D: victim is required by keeper."""
    return [
        make_record("victim", required_by=("keeper",)),
        make_record("keeper", depends=("victim",)),
    ]


def world_foreign() -> list[PackageRecord]:
    """World E: foreign (locally built) package."""
    return [make_record("localtool", origin=Origin.FOREIGN, repository="")]


def world_modified_config() -> list[PackageRecord]:
    """World H: package with backup-managed config."""
    return [
        make_record(
            "confapp",
            files=("etc/confapp.conf", "usr/bin/confapp"),
            backup_files=("etc/confapp.conf",),
        )
    ]


# --------------------------------------------------------------- fake package


@dataclass
class FakeFile:
    path: str
    size: int = 0
    mode: int = 0o644


@dataclass
class FakePackage:
    name: str
    version: str = "1.0-1"
    desc: str = ""
    arch: str = "x86_64"
    url: str = ""
    licenses: list[str] = field(default_factory=lambda: ["GPL"])
    groups: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    optdepends: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    files: list[tuple[str, int, int]] = field(default_factory=list)
    backup: list[tuple[str, str]] = field(default_factory=list)
    installdate: int = 1700000000
    packager: str = "tester"
    isize: int = 1024
    reason: int = 0
    base: str = ""
    has_scriptlet: bool = False
    db: FakeDb | None = None
    _required_by: list[str] = field(default_factory=list)
    _optional_for: list[str] = field(default_factory=list)

    def compute_requiredby(self) -> list[str]:
        return list(self._required_by)

    def compute_optionalfor(self) -> list[str] | list:
        return list(self._optional_for)


@dataclass
class FakeDb:
    name: str
    packages: list[FakePackage] = field(default_factory=list)

    @property
    def pkgcache(self) -> list[FakePackage]:
        return self.packages

    def get_pkg(self, name: str) -> FakePackage | None:
        return next((p for p in self.packages if p.name == name), None)


class FakeHandle:
    """Mimics the pyalpm.Handle surface that AlpmSession uses."""

    def __init__(self, local: FakeDb, syncs: list[FakeDb] | None = None) -> None:
        self._local = local
        self._syncs = {db.name: db for db in (syncs or [])}

    def get_localdb(self) -> FakeDb:
        return self._local

    def register_syncdb(self, name: str, flags: int) -> FakeDb:
        return self._syncs.get(name, FakeDb(name))

    def get_syncdbs(self) -> list[FakeDb]:
        return list(self._syncs.values())


def fake_handle_factory(world: list[PackageRecord], sync_map: dict[str, list[str]] | None = None):
    """Return a handle factory compatible with AlpmSession(handle_factory=...).

    sync_map: sync db name -> package names it provides (for origin tests).
    """
    sync_map = sync_map or {"extra": [str(p.name) for p in world if p.origin is Origin.OFFICIAL]}

    def factory(root: str, dbpath: str) -> FakeHandle:
        local = FakeDb("local")
        for rec in world:
            pkg = FakePackage(
                name=str(rec.name),
                version=rec.version,
                desc=rec.description,
                depends=list(rec.depends),
                provides=list(rec.provides),
                optdepends=list(rec.optdepends),
                files=[(f, 0, 0) for f in rec.files],
                backup=[(b, "") for b in rec.backup_files],
                isize=rec.size_bytes,
                installdate=rec.install_date,
                reason=0 if rec.reason is InstallReason.EXPLICIT else 1,
                _required_by=list(rec.required_by),
                _optional_for=list(rec.optional_for),
            )
            local.packages.append(pkg)
        syncs = [FakeDb(db, [FakePackage(name=n) for n in names]) for db, names in sync_map.items()]
        return FakeHandle(local, syncs)

    return factory

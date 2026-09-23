"""Domain model for CachyUninstall.

These types are intentionally free of Qt, D-Bus and pyalpm imports so the
whole domain stays unit-testable with plain Python. Adapters at the edges
(alpm_session, providers, UI models) convert to/from these types.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import NewType

PackageName = NewType("PackageName", str)


class Origin(Enum):
    """Where an installation came from, as far as we can *honestly* tell."""

    OFFICIAL = "official"  # core/extra/multilib*
    CACHYOS = "cachyos"  # cachyos* repositories
    OTHER_REPO = "other_repo"  # some other configured sync repository
    FOREIGN = "foreign"  # installed locally, not in any configured sync db
    FLATPAK = "flatpak"
    APPIMAGE = "appimage"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class InstallReason(Enum):
    EXPLICIT = "explicit"
    DEPENDENCY = "dependency"


class ProviderKind(Enum):
    PACMAN = "pacman"
    FLATPAK = "flatpak"
    APPIMAGE = "appimage"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class PackageRecord:
    """Immutable snapshot of one installed package's metadata."""

    name: PackageName
    version: str
    arch: str
    description: str
    origin: Origin
    repository: str  # sync db name it matches, or "" when foreign
    size_bytes: int
    install_date: int  # epoch seconds, 0 when unknown
    reason: InstallReason
    groups: tuple[str, ...]
    depends: tuple[str, ...]  # depstrings as stored ("foo>=1.2")
    provides: tuple[str, ...]  # virtual provisions ("sh", "libx.so=1-64")
    optdepends: tuple[str, ...]
    required_by: tuple[str, ...]
    optional_for: tuple[str, ...]
    files: tuple[str, ...]  # paths relative to root, no leading '/'
    backup_files: tuple[str, ...]
    licenses: tuple[str, ...]
    url: str

    @property
    def is_foreign(self) -> bool:
        return self.origin is Origin.FOREIGN

    @property
    def is_orphan_hint(self) -> bool:
        """Static 'installed as dependency, required by nothing' check."""
        return self.reason is InstallReason.DEPENDENCY and not self.required_by


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    PROTECTED = "protected"


class LeftoverCategory(Enum):
    CONFIGURATION = "configuration"
    APPLICATION_DATA = "application_data"
    CACHE = "cache"
    STATE = "state"
    LOGS = "logs"
    DESKTOP_INTEGRATION = "desktop_integration"
    SYSTEMD_USER_UNIT = "systemd_user_unit"
    DOCUMENTATION = "documentation"


@dataclass(frozen=True, slots=True)
class LeftoverCandidate:
    """One filesystem location that *might* belong to an installation."""

    path: Path
    category: LeftoverCategory
    confidence: Confidence
    rule_id: str  # which rule produced this (e.g. "RULE-XDG-CONFIG")
    reason: str  # human-readable "why this was found"
    size_bytes: int  # 0 when not yet measured
    owner_package: PackageName | None  # set when a package owns (part of) it
    shared_with: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RemovalImpact:
    """What removing a set of packages implies, computed from live metadata."""

    requested: tuple[PackageName, ...]
    # Packages the user must *also* agree to remove because keeping them while
    # removing targets would break them; never silently cascaded.
    blocked_by: dict[PackageName, tuple[PackageName, ...]]
    # Dependencies of the targets which would become orphans if removed
    # (presented as an explicit, separate opt-in choice).
    new_orphans: tuple[PackageName, ...]
    # Targets' deps that stay because something else needs them.
    kept_shared: dict[PackageName, tuple[PackageName, ...]]


class PlanStatus(Enum):
    VALID = "valid"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    """Approved-by-nobody-yet description of a removal. Immutable + hashable."""

    plan_id: str
    provider: ProviderKind
    targets: tuple[PackageName, ...]
    cascade: tuple[PackageName, ...]  # user-consented extra removals
    system_generation: int  # local-DB mtime marker (staleness)
    leftover_candidates: tuple[LeftoverCandidate, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def digest(self) -> str:
        """Stable digest over the parts that must not change before execute."""
        h = hashlib.sha256()
        h.update(self.provider.value.encode())
        for name in (*self.targets, *self.cascade):
            h.update(name.lower().encode())
            h.update(b"\0")
        h.update(str(self.system_generation).encode())
        return h.hexdigest()


class ResultKind(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RemovalResult:
    kind: ResultKind
    removed_packages: tuple[PackageName, ...]
    removed_paths: tuple[Path, ...]
    skipped: tuple[Path, ...]
    message: str

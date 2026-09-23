"""Structured error taxonomy for CachyUninstall.

Every failure surfaced to the user maps to one of these. Lower layers raise
them; the UI/CLI translates them into plain-language messages. No raw
tracebacks are shown to users (technical detail is attached to `detail`).
"""

from __future__ import annotations


class CuError(Exception):
    """Base class; `detail` carries machine-readable context."""

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class PackageManagerBusy(CuError):
    """The ALPM lock is held by another process."""


class AuthorizationDenied(CuError):
    """polkit denied (or cancelled) the requested action."""


class PackageNotFound(CuError):
    """Requested package is not present in the local database."""


class DependencyBlocked(CuError):
    """Removal blocked because other installed packages require the target."""

    def __init__(self, message: str, *, blockers: tuple[str, ...], detail: str = "") -> None:
        super().__init__(message, detail=detail)
        self.blockers = blockers


class OwnershipConflict(CuError):
    """A cleanup candidate is owned by an installed package/other app."""


class PathProtected(CuError):
    """The path policy refused this path."""


class FileChanged(CuError):
    """Revalidation detected a changed filesystem object (stale plan)."""


class StalePlan(CuError):
    """The approved plan no longer matches live system state."""


class PermissionDeniedFs(CuError):
    """The calling user lacks permission for the filesystem operation."""


class ProviderUnavailable(CuError):
    """A provider's underlying facility (e.g. flatpak) is not installed."""


class DatabaseUnavailable(CuError):
    """The package database cannot be opened or is inconsistent."""


class TransactionFailed(CuError):
    """The ALPM transaction raised or returned an error."""


class VerificationFailed(CuError):
    """Post-operation verification found unexpected state."""


class ProtocolError(CuError):
    """The privileged helper rejected a malformed request."""

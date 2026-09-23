"""Provider interface.

A provider owns one *installation technology* (pacman, flatpak, manual files).
It supplies application instances for the master list and technology-specific
operations. Providers must be independently disableable and must never crash
the app when their underlying facility is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cachyuninstall.core.models import Origin, ProviderKind


@dataclass(frozen=True, slots=True)
class Installation:
    """One installed instance of an application (provider-scoped)."""

    instance_id: str  # provider-unique, e.g. "pacman:firefox"
    provider: ProviderKind
    name: str  # package name or app id
    display_name: str
    version: str
    origin: Origin
    size_bytes: int
    summary: str = ""
    icon_name: str = ""
    install_date: int = 0  # epoch seconds; 0 = unknown (never fabricated)
    is_running: bool = False


class Provider(Protocol):
    kind: ProviderKind

    def is_available(self) -> bool: ...

    def list_installations(self) -> list[Installation]: ...

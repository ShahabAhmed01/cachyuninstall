"""Manual/AppImage provider — discovery only (D8).

Searches configured locations for AppImage files and user-level desktop
entries that no installed package owns. Never executes what it finds; removal
of these is intentionally out of scope in v1 (inspect + open location only),
because ownerless deletes without package verification are not defensible.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cachyuninstall.core.identity import parse_desktop_file
from cachyuninstall.core.models import Origin, ProviderKind
from cachyuninstall.core.ownership import OwnershipOracle
from cachyuninstall.providers.base import Installation

_DEFAULT_SCAN_DIRS = (
    Path("~/Applications"),
    Path("~/Apps"),
    Path("~/Downloads"),
    Path("~/.local/bin"),
)


@dataclass(slots=True)
class ManualProvider:
    oracle: OwnershipOracle | None = None
    home: Path | None = None
    scan_dirs: tuple[Path, ...] | None = None

    kind: ProviderKind = ProviderKind.MANUAL

    def is_available(self) -> bool:
        return True

    def _dirs(self) -> tuple[Path, ...]:
        dirs = self.scan_dirs or _DEFAULT_SCAN_DIRS
        return tuple(d.expanduser() for d in dirs)

    def list_installations(self) -> list[Installation]:
        out: list[Installation] = []
        seen: set[str] = set()
        for directory in self._dirs():
            if not directory.is_dir():
                continue
            try:
                children = sorted(directory.iterdir())
            except OSError:
                continue
            for child in children:
                if child.suffix.lower() != ".appimage":
                    desktop = child if child.suffix == ".desktop" else None
                    if desktop is None:
                        continue
                    entry = parse_desktop_file(desktop)
                    if entry is None or entry.hidden:
                        continue
                    app_id = entry.desktop_id
                    key = f"manual:{app_id}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        Installation(
                            instance_id=key,
                            provider=ProviderKind.MANUAL,
                            name=app_id,
                            display_name=entry.name or app_id,
                            version="",
                            origin=Origin.MANUAL,
                            size_bytes=0,
                            summary=entry.comment,
                            icon_name=entry.icon,
                        )
                    )
                    continue
                app_id = child.stem
                key = f"appimage:{app_id}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    Installation(
                        instance_id=key,
                        provider=ProviderKind.APPIMAGE,
                        name=app_id,
                        display_name=app_id,
                        version="",
                        origin=Origin.APPIMAGE,
                        size_bytes=child.stat().st_size if child.is_file() else 0,
                        summary="AppImage (installation source unverified)",
                    )
                )
        return out

"""User settings at ~/.config/cachyuninstall/settings.json.

Plain JSON (atomic write), versioned, enum-typed access. Unknown keys are
ignored; missing keys fall back to declared defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path("~/.config/cachyuninstall").expanduser()
_SETTINGS_PATH = CONFIG_DIR / "settings.json"


@dataclass(slots=True)
class Settings:
    confirm_destructive: bool = True
    use_quarantine: bool = True
    keep_configuration: bool = True
    show_low_confidence: bool = False
    follow_system_theme: bool = True
    reduced_motion: bool = False
    scan_cache: bool = True
    scan_appimage_dirs: bool = True
    debug_logging: bool = False
    window_geometry: str = ""  # base64 QByteArray from saveGeometry()

    @property
    def path(self) -> Path:
        return _SETTINGS_PATH


def load_settings(path: Path | None = None) -> Settings:
    target = path or _SETTINGS_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("settings not an object")
    except (OSError, ValueError, json.JSONDecodeError):
        return Settings()
    defaults = asdict(Settings())
    # Keys are derived from the dataclass fields themselves, so the merge is
    # schema-valid by construction; values are coerced to the declared types.
    merged: dict[str, object] = {k: _coerce(raw.get(k, v), v) for k, v in defaults.items()}
    return Settings(**merged)  # type: ignore[arg-type]  # keys match the schema


def _coerce(value: object, default: object) -> object:
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return value


def save_settings(settings: Settings, path: Path | None = None) -> None:
    target = path or _SETTINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, target)

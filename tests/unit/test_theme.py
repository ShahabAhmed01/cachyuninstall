"""Theme integrity: resource files must match the embedded source of truth."""

from __future__ import annotations

from pathlib import Path

from cachyuninstall.ui.theme import DARK_QSS, LIGHT_QSS

ROOT = Path(__file__).resolve().parents[2]


def test_theme_files_match_embedded() -> None:
    assert (ROOT / "resources/themes/dark.qss").read_text() == DARK_QSS
    assert (ROOT / "resources/themes/light.qss").read_text() == LIGHT_QSS


def test_stylesheets_are_balanced() -> None:
    for name, qss in (("dark", DARK_QSS), ("light", LIGHT_QSS)):
        assert qss.count("{") == qss.count("}"), name

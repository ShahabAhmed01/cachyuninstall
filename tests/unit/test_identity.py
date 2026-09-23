"""Desktop-entry parsing and identity-graph tests (§53, §152)."""

from __future__ import annotations

from pathlib import Path

from cachyuninstall.core.identity import (
    build_identity_index,
    parse_desktop_file,
)
from cachyuninstall.core.models import PackageName
from tests.harness.fake_alpm import make_record


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_parse_basic(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "org.example.App.desktop",
        """[Desktop Entry]
Type=Application
Name=Cool App
Name[de]=Coole App
GenericName=Tool
Comment=Does things
Exec=/usr/bin/coolapp --flag %f
Icon=coolapp
Categories=Utility;Development;
Keywords=cool;tool;
MimeType=text/plain;
StartupWMClass=coolapp
Terminal=false
""",
    )
    entry = parse_desktop_file(f)
    assert entry is not None
    assert entry.desktop_id == "org.example.App"
    assert entry.name == "Cool App"
    assert entry.categories == ("Utility", "Development")
    assert entry.exec_binary_guess == "coolapp"
    assert entry.startup_wm_class == "coolapp"


def test_parse_localized(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "a.desktop",
        "[Desktop Entry]\nType=Application\nName=Base\nName[de]=Basis\n",
    )
    de = parse_desktop_file(f, locale="de_DE.UTF-8")
    assert de is not None and de.name == "Basis"


def test_non_application_returns_none(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "link.desktop",
        "[Desktop Entry]\nType=Link\nName=X\nURL=https://example.com\n",
    )
    assert parse_desktop_file(f) is None


def test_malformed_returns_none(tmp_path: Path) -> None:
    f = _write(tmp_path / "broken.desktop", "no equals sign anywhere\n[Desktop Entry\n")
    assert parse_desktop_file(f) is None


def test_exec_is_never_used_for_discovery_execution(tmp_path: Path) -> None:
    # A hostile Exec line is stored as inert metadata only (§177, §287).
    marker = tmp_path / "pwned"
    hostile = _write(
        tmp_path / "evil.desktop",
        f"[Desktop Entry]\nType=Application\nName=X\nExec=touch {marker}\n",
    )
    entry = parse_desktop_file(hostile)
    assert entry is not None
    assert not marker.exists()
    assert "touch" in entry.exec_line


def test_identity_index_uses_desktop_files(tmp_path: Path) -> None:
    _write(
        tmp_path / "usr/share/applications/co.desktop",
        "[Desktop Entry]\nType=Application\nName=Co\nExec=/usr/bin/co %U\nIcon=co\n",
    )
    pkg = make_record(
        "co",
        files=("usr/share/applications/co.desktop", "usr/bin/co"),
    )
    index = build_identity_index([pkg], root=tmp_path)
    ident = index[PackageName("co")]
    assert ident.display_name == "Co"
    assert "co" in ident.executables
    assert ident.icon_names == ("co",)
    assert "co" in ident.candidate_names


def test_candidate_names_include_desktop_tail(tmp_path: Path) -> None:
    pkg = make_record("co", files=("usr/bin/co",))
    idx = build_identity_index([pkg], root=tmp_path)
    ident = idx[PackageName("co")]
    assert "co" in ident.candidate_names

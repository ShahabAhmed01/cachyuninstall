"""Scope-explicit flatpak argv (QA M ambiguity, physical probe D24).

The same app id can be installed in the system AND user scope at once.
`flatpak uninstall <id>` without a scope flag then prompts interactively
("Similar installed refs found … Which do you want to use?") — observed
physically in the disposable container — which would hang the GUI's
30-second captured subprocess. The argv must pin the scope.
"""

from __future__ import annotations

import pytest

from cachyuninstall.providers.flatpak import FlatpakProvider


def test_uninstall_argv_system_scope_is_explicit() -> None:
    argv = FlatpakProvider().build_uninstall_argv("org.gnome.Calculator", "system")
    assert argv == [
        "flatpak",
        "uninstall",
        "--system",
        "--delete-data",
        "-y",
        "org.gnome.Calculator",
    ]


def test_uninstall_argv_user_scope_is_explicit() -> None:
    argv = FlatpakProvider().build_uninstall_argv("org.gnome.Calculator", "user")
    assert argv == [
        "flatpak",
        "uninstall",
        "--user",
        "--delete-data",
        "-y",
        "org.gnome.Calculator",
    ]


def test_uninstall_argv_never_shell_interpolated() -> None:
    argv = FlatpakProvider().build_uninstall_argv("org.gnome.Calculator; rm -rf /", "system")
    assert argv[-1] == "org.gnome.Calculator; rm -rf /"  # single opaque argument
    assert all(" " not in a or a == argv[-1] for a in argv)


def test_info_json_pins_scope_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FlatpakProvider()
    seen: list[list[str]] = []

    def fake_run(args: list[str]) -> str:
        seen.append(list(args))
        return "Ref: app/org.gnome.Calculator/x86_64/stable\nSize: 1,0 MB\n"

    monkeypatch.setattr(provider, "_run", fake_run)
    out = provider.info_json("org.gnome.Calculator", "system")
    assert seen == [["info", "--system", "--show-size", "org.gnome.Calculator"]]
    assert "Ref" in out

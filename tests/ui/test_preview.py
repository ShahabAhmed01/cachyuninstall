"""Preview dialog behavior (§94-96, D9)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from cachyuninstall.core.models import (
    Confidence,
    LeftoverCandidate,
    LeftoverCategory,
    PackageName,
    RemovalImpact,
)
from cachyuninstall.persistence.settings import Settings
from cachyuninstall.ui.preview_dialog import PreviewDialog


def _impact() -> RemovalImpact:
    return RemovalImpact(
        requested=(PackageName("firefox"),),
        blocked_by={},
        new_orphans=(PackageName("libonly"),),
        kept_shared={PackageName("gtk4"): (PackageName("app-b"),)},
    )


def _candidates() -> list[LeftoverCandidate]:
    home = Path.home()
    return [
        LeftoverCandidate(
            path=home / ".config" / "firefox",
            category=LeftoverCategory.CONFIGURATION,
            confidence=Confidence.HIGH,
            rule_id="RULE-XDG-CONFIG",
            reason="config",
            size_bytes=1024,
            owner_package=None,
        ),
        LeftoverCandidate(
            path=home / ".cache" / "firefox",
            category=LeftoverCategory.CACHE,
            confidence=Confidence.HIGH,
            rule_id="RULE-XDG-CACHE",
            reason="cache",
            size_bytes=2048,
            owner_package=None,
        ),
        LeftoverCandidate(
            path=home / ".local" / "share" / "firefox",
            category=LeftoverCategory.APPLICATION_DATA,
            confidence=Confidence.PROTECTED,
            rule_id="RULE-XDG-DATA",
            reason="shared",
            size_bytes=0,
            owner_package=None,
        ),
    ]


def test_defaults_keep_configuration(qtbot) -> None:
    dialog = PreviewDialog("Firefox", _impact(), _candidates(), Settings())
    qtbot.addWidget(dialog)
    # Configuration must NOT be preselected (D9).
    for box, cand in dialog._checkboxes:
        if cand.category is LeftoverCategory.CONFIGURATION:
            assert not box.isChecked()
        if cand.confidence is Confidence.PROTECTED:
            raise AssertionError("protected items must never be selectable")


def test_accept_collects_only_selected(qtbot) -> None:
    dialog = PreviewDialog("Firefox", _impact(), _candidates(), Settings())
    qtbot.addWidget(dialog)
    for box, cand in dialog._checkboxes:
        box.setChecked(cand.category is LeftoverCategory.CACHE)
    dialog._accept()
    choice = dialog.choice()
    assert choice.approved
    assert len(choice.selected_leftovers) == 1
    assert choice.selected_leftovers[0].category is LeftoverCategory.CACHE


def test_orphan_cascade_opt_in(qtbot) -> None:
    dialog = PreviewDialog("Firefox", _impact(), _candidates(), Settings())
    qtbot.addWidget(dialog)
    assert dialog.chk_orphans is not None and not dialog.chk_orphans.isChecked()
    dialog.chk_orphans.setChecked(True)
    dialog._accept()
    assert dialog.choice().remove_orphan_deps


def test_cancel_means_nothing(qtbot) -> None:
    dialog = PreviewDialog("Firefox", _impact(), _candidates(), Settings())
    qtbot.addWidget(dialog)
    dialog.reject()
    assert not dialog.choice().approved
    assert dialog.choice().selected_leftovers == []

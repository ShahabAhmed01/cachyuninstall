"""Removal preview — the signature screen (§94).

Structure: REMOVE / additional dependencies (opt-in) / KEEP (shared) /
USER DATA (per-category opt-in checkboxes with reasons) / UNCERTAIN
(hidden unless explicitly enabled) / PROTECTED (informational).

Defaults (D9): configuration is kept; cache is offered but not preselected
unless the user opts in. Low-confidence candidates stay hidden unless the
user enabled them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cachyuninstall.core.models import (
    Confidence,
    LeftoverCandidate,
    LeftoverCategory,
    RemovalImpact,
)
from cachyuninstall.persistence.settings import Settings
from cachyuninstall.ui.package_model import human_size


@dataclass(slots=True)
class PreviewChoice:
    approved: bool
    remove_orphan_deps: bool
    selected_leftovers: list[LeftoverCandidate] = field(default_factory=list)
    use_quarantine: bool = True


class PreviewDialog(QDialog):
    def __init__(
        self,
        subject: str,
        impact: RemovalImpact,
        leftovers: list[LeftoverCandidate],
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Uninstall {subject}")
        self.setMinimumSize(560, 480)
        self._leftovers = leftovers
        self._choice = PreviewChoice(approved=False, remove_orphan_deps=False)
        self._checkboxes: list[tuple[QCheckBox, LeftoverCandidate]] = []
        self._build(subject, impact, leftovers, settings)

    # ------------------------------------------------------------------ UI
    def _build(
        self,
        subject: str,
        impact: RemovalImpact,
        leftovers: list[LeftoverCandidate],
        settings: Settings,
    ) -> None:
        outer = QVBoxLayout(self)
        title = QLabel(f"Uninstall {subject}")
        title.setProperty("role", "title")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._build_remove_section(body_layout, impact)
        self.chk_orphans = self._build_orphans_section(body_layout, impact)
        self._build_keep_section(body_layout, impact)
        visible, protected = self._split_candidates(leftovers, settings)
        self._build_data_section(body_layout, visible, settings)
        self._build_protected_section(body_layout, protected)

        self.chk_quarantine = QCheckBox("Move files to quarantine instead of deleting")
        self.chk_quarantine.setChecked(settings.use_quarantine)
        self.chk_quarantine.setToolTip(
            "Files are moved to ~/.local/share/cachyuninstall/quarantine and can be restored."
        )
        body_layout.addWidget(self.chk_quarantine)
        body_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("Uninstall")
            ok_btn.setProperty("danger", True)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------ sections
    def _build_remove_section(self, layout: QVBoxLayout, impact: RemovalImpact) -> None:
        box = QGroupBox(f"Packages to remove ({len(impact.requested)})")
        inner = QVBoxLayout(box)
        for name in impact.requested:
            inner.addWidget(QLabel(f"• {name}"))
        layout.addWidget(box)

    def _build_orphans_section(self, layout: QVBoxLayout, impact: RemovalImpact) -> QCheckBox | None:
        if not impact.new_orphans:
            return None
        box = QGroupBox("Dependencies no longer needed afterwards")
        inner = QVBoxLayout(box)
        checkbox = QCheckBox(f"Also remove {len(impact.new_orphans)} unneeded dependencies")
        checkbox.setChecked(False)
        checkbox.setToolTip("These packages are currently only required by what you are removing.")
        inner.addWidget(checkbox)
        for name in impact.new_orphans:
            row = QLabel(f"• {name}")
            row.setContentsMargins(20, 0, 0, 0)
            inner.addWidget(row)
        layout.addWidget(box)
        return checkbox

    def _build_keep_section(self, layout: QVBoxLayout, impact: RemovalImpact) -> None:
        if not impact.kept_shared:
            return
        box = QGroupBox("Kept - required by other applications")
        inner = QVBoxLayout(box)
        for name, users in impact.kept_shared.items():
            inner.addWidget(QLabel(f"• {name} - needed by: {', '.join(users[:4])}"))
        layout.addWidget(box)

    @staticmethod
    def _split_candidates(
        leftovers: list[LeftoverCandidate], settings: Settings
    ) -> tuple[list[LeftoverCandidate], list[LeftoverCandidate]]:
        visible = [
            c
            for c in leftovers
            if c.confidence is not Confidence.PROTECTED
            and (settings.show_low_confidence or c.confidence is not Confidence.LOW)
        ]
        protected = [c for c in leftovers if c.confidence is Confidence.PROTECTED]
        return visible, protected

    def _build_data_section(
        self, layout: QVBoxLayout, visible: list[LeftoverCandidate], settings: Settings
    ) -> None:
        if not visible:
            return
        box = QGroupBox("Application data (select what to remove)")
        inner = QVBoxLayout(box)
        note = QLabel("Configuration is kept by default so you do not lose settings.")
        note.setProperty("role", "subtitle")
        inner.addWidget(note)
        for cand in visible:
            row_box = QCheckBox(
                f"{cand.path}   ·   {human_size(cand.size_bytes)}   ·   {cand.category.value}"
            )
            row_box.setToolTip(cand.reason)
            row_box.setChecked(cand.category is LeftoverCategory.CACHE and not settings.keep_configuration)
            self._checkboxes.append((row_box, cand))
            inner.addWidget(row_box)
            reason = QLabel(cand.reason)
            reason.setProperty("role", "subtitle")
            reason.setContentsMargins(26, 0, 0, 6)
            inner.addWidget(reason)
        layout.addWidget(box)

    @staticmethod
    def _build_protected_section(layout: QVBoxLayout, protected: list[LeftoverCandidate]) -> None:
        if not protected:
            return
        box = QGroupBox("Protected (will not be touched)")
        inner = QVBoxLayout(box)
        for cand in protected:
            inner.addWidget(QLabel(f"• {cand.path}"))
            why = QLabel(cand.reason)
            why.setProperty("role", "subtitle")
            why.setContentsMargins(20, 0, 0, 6)
            inner.addWidget(why)
        layout.addWidget(box)

    # ---------------------------------------------------------------- result
    def _accept(self) -> None:
        selected = [cand for box, cand in self._checkboxes if box.isChecked()]
        self._choice = PreviewChoice(
            approved=True,
            remove_orphan_deps=bool(self.chk_orphans and self.chk_orphans.isChecked()),
            selected_leftovers=selected,
            use_quarantine=self.chk_quarantine.isChecked(),
        )
        self.accept()

    def choice(self) -> PreviewChoice:
        return self._choice

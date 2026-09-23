"""Details panel for the selected installation.

Shows package metadata, dependencies, reverse dependencies and the cleanup
analysis summary. Raw metadata stays expandable but visible — Arch users must
always be able to see the real package facts (§211).
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cachyuninstall.core.models import PackageRecord
from cachyuninstall.ui.package_model import human_date, human_size, origin_label

_LOOKUP = Callable[[str], "PackageRecord | None"]


class DetailsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("details")
        self._record: PackageRecord | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.title = QLabel("Select an application")
        self.title.setProperty("role", "title")
        layout.addWidget(self.title)

        self.subtitle = QLabel("")
        self.subtitle.setProperty("role", "subtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.form_widget = QWidget()
        self._form = QFormLayout(self.form_widget)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.form_widget)

        self.deps_title = QLabel("")
        self.deps_title.setProperty("role", "subtitle")
        layout.addWidget(self.deps_title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Kind"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(140)
        layout.addWidget(self.tree, 1)

        self.raw = QTextBrowser()
        self.raw.setMaximumHeight(140)
        self.raw.setVisible(False)
        layout.addWidget(self.raw)

        self.raw_toggle = QPushButton("Show raw package metadata")
        self.raw_toggle.clicked.connect(self._toggle_raw)
        layout.addWidget(self.raw_toggle, 0, Qt.AlignmentFlag.AlignLeft)

    # ------------------------------------------------------------ population
    def show_package(self, record: PackageRecord | None) -> None:
        self._record = record
        self.tree.clear()
        if record is None:
            self.title.setText("Select an application")
            self.subtitle.clear()
            self._clear_form()
            self.raw_toggle.setVisible(False)
            return

        self.title.setText(record.name)
        self.subtitle.setText(record.description)
        self._set_form(record)
        self._populate_tree(record)
        self.raw_toggle.setVisible(True)
        self.raw.setPlainText(self._raw_text(record))
        self.raw.setVisible(False)
        self.raw_toggle.setText("Show raw package metadata")

    def _set_form(self, r: PackageRecord) -> None:
        self._clear_form()
        self._form.addRow("Package", QLabel(r.name))
        self._form.addRow("Version", QLabel(r.version))
        self._form.addRow("Origin", QLabel(origin_label(r.origin)))
        if r.repository:
            self._form.addRow("Repository", QLabel(r.repository))
        self._form.addRow("Installed size", QLabel(human_size(r.size_bytes)))
        self._form.addRow("Installed on", QLabel(human_date(r.install_date)))
        self._form.addRow(
            "Installed as",
            QLabel("explicitly installed" if r.reason.value == "explicit" else "dependency"),
        )
        if r.url:
            self._form.addRow("Homepage", QLabel(f"<a href='{r.url}'>{r.url}</a>"))
        if r.licenses:
            self._form.addRow("License", QLabel(", ".join(r.licenses)))
        if r.groups:
            self._form.addRow("Groups", QLabel(", ".join(r.groups)))

    def _populate_tree(self, r: PackageRecord) -> None:
        def fill(title: str, items: tuple[str, ...], kind: str) -> None:
            root = QTreeWidgetItem([f"{title} ({len(items)})", ""])
            self.tree.addTopLevelItem(root)
            for item in items:
                QTreeWidgetItem(root, [item, kind])

        fill("Depends on", r.depends, "dependency")
        fill("Required by", r.required_by, "reverse dependency")
        fill("Optional for", r.optional_for, "optional")
        fill("Backup files", r.backup_files, "config")
        fill("Installed files", tuple(list(r.files)[:500]), "file")
        self.tree.expandToDepth(0)  # depth 0 keeps list compact; user expands on demand
        self.deps_title.setText(f"{len(r.depends)} dependencies · required by {len(r.required_by)}")

    # --------------------------------------------------------------- helpers
    def _toggle_raw(self) -> None:
        visible = not self.raw.isVisible()
        self.raw.setVisible(visible)
        self.raw_toggle.setText("Hide raw package metadata" if visible else "Show raw package metadata")

    def _clear_form(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)

    @staticmethod
    def _raw_text(r: PackageRecord) -> str:
        lines = [
            f"name={r.name}",
            f"version={r.version}",
            f"arch={r.arch}",
            f"origin={r.origin.value}",
            f"repo={r.repository}",
            f"size={r.size_bytes}",
            f"installdate={r.install_date}",
            f"reason={r.reason.value}",
            f"groups={', '.join(r.groups) or '-'}",
            "",
            "[depends]",
            *r.depends,
            "",
            "[provides]",
            *r.provides,
            "",
            "[optdepends]",
            *r.optdepends,
        ]
        return "\n".join(lines)

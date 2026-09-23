"""Progress dialog fed by real libalpm events.

Cancellation is honest (D5): Cancel is only presented while the state is
cancellable; during commit the button changes to a disabled state explaining
that interruption mid-transaction may not be reversible.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cachyuninstall.privilege.backend import TxEvent


class ProgressDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        self.status = QLabel("Preparing…")
        layout.addWidget(self.status)

        self.current = QLabel("")
        self.current.setProperty("role", "subtitle")
        layout.addWidget(self.current)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)

        self.cancel = QPushButton("Cancel")
        layout.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignRight)
        self._on_cancel: Callable[[], None] | None = None
        self.cancel.clicked.connect(self._cancel_clicked)
        self._cancelled = False

    def on_cancel(self, fn: Callable[[], None]) -> None:
        self._on_cancel = fn

    def _cancel_clicked(self) -> None:
        self._cancelled = True
        self.cancel.setEnabled(False)
        self.cancel.setText("Cancelling…")
        if self._on_cancel:
            self._on_cancel()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # ------------------------------------------------------------------ feed
    def handle_event(self, event: TxEvent) -> None:
        if event.kind == "progress" and event.percent >= 0:
            self.bar.setValue(event.percent)
            self.current.setText(f"{event.target} ({event.current}/{event.total})")
        elif event.kind == "stage":
            self.status.setText(event.message)
            if event.target:
                self.current.setText(event.target)
        elif event.kind == "log":
            self.current.setText(event.message[:120])

    def mark_commit_phase(self) -> None:
        self.cancel.setEnabled(False)
        self.cancel.setText("Committing — cannot safely cancel")

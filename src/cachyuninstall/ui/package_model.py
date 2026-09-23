"""QAbstractTableModel over installations + QSortFilterProxyModel filtering.

Display set is a *snapshot*: Installation objects are plain domain values, so
the model never holds locks and never calls providers from paint code.
"""

from __future__ import annotations

import time
from typing import Any

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PyQt6.QtGui import QIcon

from cachyuninstall.core.models import Origin
from cachyuninstall.providers.base import Installation

COLUMNS = ("Name", "Version", "Source", "Installed", "Size")

_ORIGIN_LABEL = {
    Origin.OFFICIAL: "Official",
    Origin.CACHYOS: "CachyOS",
    Origin.OTHER_REPO: "Repository",
    Origin.FOREIGN: "Foreign/AUR?",
    Origin.FLATPAK: "Flatpak",
    Origin.APPIMAGE: "AppImage",
    Origin.MANUAL: "Manual",
    Origin.UNKNOWN: "Unknown",
}


def human_size(size: int) -> str:
    if size < 0:
        return "—"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


def human_date(epoch: int) -> str:
    if epoch <= 0:
        return "unknown"
    return time.strftime("%Y-%m-%d", time.localtime(epoch))


def origin_label(origin: Origin) -> str:
    return _ORIGIN_LABEL.get(origin, origin.value)


class InstallationModel(QAbstractTableModel):
    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[Installation] = []

    # ------------------------------------------------------------------ data
    def set_rows(self, rows: list[Installation]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def at(self, row: int) -> Installation | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    # -------------------------------------------------------- Qt boilerplate
    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = 0) -> Any:
        if not index.isValid():
            return None
        item = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            col = index.column()
            if col == 0:
                return item.display_name or item.name
            if col == 1:
                return item.version or "—"
            if col == 2:
                return origin_label(item.origin)
            if col == 3:
                return human_date(item.install_date)
            if col == 4:
                return human_size(item.size_bytes)
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            if item.icon_name:
                icon = QIcon.fromTheme(item.icon_name)
                if not icon.isNull():
                    return icon
            return QIcon.fromTheme("application-x-executable")
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{item.name}\n{item.summary}"
        if role == Qt.ItemDataRole.UserRole:
            return item.instance_id
        return None

    def lessThan_key(self, row: int, column: int) -> Any:
        item = self._rows[row]
        if column == 4:
            return item.size_bytes
        return self.data(self.index(row, column), Qt.ItemDataRole.DisplayRole) or ""


class InstallationFilter(QSortFilterProxyModel):
    """Search across name/description/id; origin filter chips."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._origin_filter: str = ""
        self._query: str = ""
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_query(self, text: str) -> None:
        self._query = text.strip().lower()
        self.invalidateRowsFilter()

    def set_origin_filter(self, origin_value: str) -> None:
        self._origin_filter = origin_value
        self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model: InstallationModel = self.sourceModel()  # type: ignore[assignment]
        item = model.at(source_row)
        if item is None:
            return False
        if self._origin_filter and item.origin.value != self._origin_filter:
            return False
        if not self._query:
            return True
        hay = " ".join((item.name, item.display_name, item.summary, item.instance_id)).lower()
        return self._query in hay

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model: InstallationModel = self.sourceModel()  # type: ignore[assignment]
        if left.column() == 4:
            lhs = model.at(left.row())
            rhs = model.at(right.row())
            if lhs and rhs:
                return lhs.size_bytes < rhs.size_bytes
        return super().lessThan(left, right)

"""QSS theming with named design tokens (§16/17).

Widgets use dynamic properties ([state="..."], [role="..."]) addressed below.
Palettes are Breeze-inspired. No phantom CSS transitions (Qt style sheets do
not support `transition:`) — animation uses Qt's animation framework (§15).

The strings here are canonical; `resources/themes/*.qss` are generated
mirrors for reviewers/packagers and are kept byte-identical by a unit test.
"""

from __future__ import annotations

DARK = "dark"
LIGHT = "light"

DARK_QSS = """
* {
    color: #fcfcfc;
    selection-background-color: #3daee9;
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog { background: #232629; }
QWidget#details { background: #2a2e32; border-left: 1px solid #31363b; }
QLabel[role="title"] { font-size: 14pt; font-weight: 600; }
QLabel[role="subtitle"] { color: #b0b6bb; }
QLabel[state="danger"] { color: #da4453; }
QLabel[state="warn"]   { color: #f67400; }
QLabel[state="ok"]     { color: #27ae60; }
QTableView {
    background: #232629;
    alternate-background-color: #2a2e32;
    gridline-color: #31363b;
    border: none;
}
QHeaderView::section {
    background: #2a2e32;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid #31363b;
}
QLineEdit {
    background: #2a2e32;
    border: 1px solid #31363b;
    border-radius: 3px;
    padding: 5px 8px;
}
QLineEdit:focus { border-color: #3daee9; }
QPushButton {
    background: #2a2e32;
    border: 1px solid #31363b;
    border-radius: 3px;
    padding: 6px 14px;
}
QPushButton:hover { border-color: #3daee9; }
QPushButton[default="true"] {
    background: #3daee9;
    color: #0d1114;
    font-weight: 600;
}
QPushButton[danger="true"] {
    background: #da4453;
    color: #ffffff;
    font-weight: 600;
}
QTabBar::tab { padding: 6px 16px; }
QTabBar::tab:selected { border-bottom: 2px solid #3daee9; color: #3daee9; }
QTreeView, QListView { background: #232629; border: 1px solid #31363b; }
QGroupBox {
    border: 1px solid #31363b;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #3daee9; }
QProgressBar { background: #2a2e32; border-radius: 3px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #3daee9; border-radius: 3px; }
QToolTip { background: #31363b; border: 1px solid #3daee9; padding: 4px; }
"""

LIGHT_QSS = """
* {
    color: #232629;
    selection-background-color: #3daee9;
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog { background: #f5f6f7; }
QWidget#details { background: #ffffff; border-left: 1px solid #d4d7da; }
QLabel[role="title"] { font-size: 14pt; font-weight: 600; }
QLabel[role="subtitle"] { color: #5c6166; }
QLabel[state="danger"] { color: #c0392b; }
QLabel[state="warn"]   { color: #da8c00; }
QLabel[state="ok"]     { color: #1e8e4e; }
QTableView {
    background: #ffffff;
    alternate-background-color: #f5f6f7;
    gridline-color: #e4e6e8;
    border: none;
}
QHeaderView::section {
    background: #f5f6f7;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid #d4d7da;
}
QLineEdit {
    background: #ffffff;
    border: 1px solid #d4d7da;
    border-radius: 3px;
    padding: 5px 8px;
}
QLineEdit:focus { border-color: #3daee9; }
QPushButton {
    background: #ffffff;
    border: 1px solid #d4d7da;
    border-radius: 3px;
    padding: 6px 14px;
}
QPushButton:hover { border-color: #3daee9; }
QPushButton[default="true"] {
    background: #3daee9;
    color: #ffffff;
    font-weight: 600;
}
QPushButton[danger="true"] {
    background: #c0392b;
    color: #ffffff;
    font-weight: 600;
}
QTabBar::tab { padding: 6px 16px; }
QTabBar::tab:selected { border-bottom: 2px solid #3daee9; color: #206d9c; }
QTreeView, QListView { background: #ffffff; border: 1px solid #d4d7da; }
QGroupBox {
    border: 1px solid #d4d7da;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #206d9c; }
QProgressBar { background: #ffffff; border: 1px solid #d4d7da; border-radius: 3px; height: 8px; }
QProgressBar::chunk { background: #3daee9; border-radius: 3px; }
QToolTip { background: #ffffff; border: 1px solid #3daee9; padding: 4px; }
"""


def stylesheet(name: str) -> str:
    return LIGHT_QSS if name == LIGHT else DARK_QSS

"""GUI bootstrap (§115 single instance, §83 startup).

Order of operations: QApplication → settings/theme → single-instance guard →
background load → MainWindow. No network, no AUR helper, no sync db refresh —
startup is fully offline (§174, §229).
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QProgressBar, QVBoxLayout

from cachyuninstall import APP_ID, APP_NAME
from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.persistence.history import HistoryStore
from cachyuninstall.persistence.settings import load_settings
from cachyuninstall.privilege.client import HelperClient
from cachyuninstall.providers.flatpak import FlatpakProvider
from cachyuninstall.providers.manual import ManualProvider
from cachyuninstall.providers.pacman import PacmanProvider
from cachyuninstall.ui.main_window import AppState, MainWindow
from cachyuninstall.ui.theme import DARK, LIGHT, stylesheet
from cachyuninstall.ui.workers import Executor

LOG = logging.getLogger("cachyuninstall")


def _detect_dark(app: QApplication) -> bool:
    color = app.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128


def run_gui() -> int:
    QApplication.setApplicationName(APP_ID)
    QApplication.setOrganizationName("CachyOS")
    app = QApplication(sys.argv)

    settings = load_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug_logging else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    theme = DARK if _detect_dark(app) else LIGHT
    app.setStyleSheet(stylesheet(theme))

    splash = QDialog()
    splash.setWindowTitle(APP_NAME)
    lay = QVBoxLayout(splash)
    lay.addWidget(QLabel(f"{APP_NAME} is reading the package database…"))
    bar = QProgressBar()
    bar.setRange(0, 0)  # indeterminate — enumeration duration isn't predictable
    lay.addWidget(bar)
    splash.show()
    app.processEvents()

    def load() -> AppState | Exception:
        try:
            session = AlpmSession()
            session.open()
            # Phase 1: light rows — no syncdb probing, no per-package file
            # lists or reverse-deps (those are the expensive fields, §83/§145).
            packages = session.packages(with_origin_resolution=False, full_detail=False)
            pacman = PacmanProvider(session)
            flatpak = FlatpakProvider()
            manual = ManualProvider()
            installations = pacman.list_installations_light(packages)
            installations += flatpak.list_installations()
            installations += manual.list_installations()
            return AppState(
                session=session,
                packages=packages,
                identities={},  # filled by the enrichment pass
                settings=settings,
                history=HistoryStore(),
                helper=HelperClient(),
                flatpak=flatpak,
                installations=installations,
            )
        except Exception as exc:  # surfaced in the GUI, not at import time
            return exc

    holder: dict[str, object] = {}

    def loaded(result: object) -> None:
        holder["state"] = result
        app.quit()

    def failed(reason: str) -> None:
        holder["state"] = RuntimeError(reason)
        app.quit()

    Executor.run(load, loaded, failed)
    app.exec()  # runs only until load completes
    result = holder.get("state")
    splash.close()

    if isinstance(result, Exception):
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.critical(
            None,
            f"{APP_NAME} - startup failed",
            f"The package database could not be read.\n\n{result}",
        )
        return 2
    if not isinstance(result, AppState):
        raise RuntimeError("load produced unexpected result")  # unreachable guard

    window = MainWindow(result)
    window.show()
    # NOTE: load_orphans() intentionally NOT called here. At this point the
    # packages are light-detail (no reverse-dep computation), so
    # is_orphan_hint would over-report EVERY installed-as-dependency package
    # as an orphan. The orphan tab is filled from the enriched packages in
    # _start_enrichment's apply() below.
    window.populate_cleanup_apps()
    _start_enrichment(window)
    return app.exec()


def _start_enrichment(window: MainWindow) -> None:
    """Phase 2 (background): resolve true origins into the shown rows.

    Startup shows the table immediately from the local DB; sync-db probing is
    slower, so origin labels finalize in the background (§83/§145). The same
    pipeline runs again after each removal (``MainWindow.refresh_state``).
    """
    window.refresh_state()

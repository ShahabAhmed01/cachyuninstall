"""Main window — master/detail application list + tabs.

Owns no business logic beyond orchestration:
  * loading: providers in worker → model;
  * details: lookup only;
  * uninstall: planner + scanner (worker) → PreviewDialog → HelperClient
    (async) → verification (worker) → history + refresh.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.errors import DependencyBlocked
from cachyuninstall.core.filesystem import CleanupExecutor, CleanupReport, Quarantine
from cachyuninstall.core.identity import Identity, build_identity_index
from cachyuninstall.core.leftovers import LeftoverScanner, ScanContext
from cachyuninstall.core.models import (
    Confidence,
    LeftoverCandidate,
    Origin,
    PackageName,
    PackageRecord,
    ProviderKind,
    RemovalImpact,
    RemovalPlan,
)
from cachyuninstall.core.ownership import DictOwnerIndex, OwnershipOracle
from cachyuninstall.core.paths import PathPolicy
from cachyuninstall.core.planner import RemovalPlanner
from cachyuninstall.core.process import running_pids_for
from cachyuninstall.persistence.history import HistoryKind, HistoryStore
from cachyuninstall.persistence.settings import Settings
from cachyuninstall.privilege.client import HelperClient
from cachyuninstall.privilege.protocol import HelperReply
from cachyuninstall.providers.base import Installation
from cachyuninstall.providers.flatpak import FlatpakProvider
from cachyuninstall.providers.manual import ManualProvider
from cachyuninstall.providers.pacman import PacmanProvider
from cachyuninstall.ui.details_panel import DetailsPanel
from cachyuninstall.ui.package_model import InstallationFilter, InstallationModel, human_size
from cachyuninstall.ui.preview_dialog import PreviewChoice, PreviewDialog
from cachyuninstall.ui.progress_dialog import ProgressDialog
from cachyuninstall.ui.workers import Executor

LOG = logging.getLogger("cachyuninstall.window")


@dataclass(slots=True)
class AppState:
    """Shared snapshot + services handed to the window at startup."""

    session: AlpmSession
    packages: list[PackageRecord]
    identities: dict[PackageName, Identity]
    settings: Settings
    history: HistoryStore
    helper: HelperClient
    flatpak: FlatpakProvider
    installations: list[Installation]


def _fresh_oracle() -> tuple[AlpmSession, OwnershipOracle]:
    """Per-worker session + freshly built ownership oracle.

    The owner index is expensive (~6s on a 1.4k-package system), so it is
    built lazily inside analysis workers, never at startup (§145). This also
    guarantees ownership data is re-read before every execution (D3).
    """
    session = AlpmSession()
    session.open()
    return session, OwnershipOracle(DictOwnerIndex(session.refresh_owner_index()))


_ORIGIN_CHOICES = (
    ("", "All sources"),
    ("official", "Official"),
    ("cachyos", "CachyOS"),
    ("foreign", "Foreign / unknown repo"),
    ("flatpak", "Flatpak"),
    ("appimage", "AppImage"),
    ("manual", "Manual"),
)


class MainWindow(QMainWindow):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self._state = state
        self.setWindowTitle("CachyUninstall")
        self.resize(1024, 680)

        self._model = InstallationModel(self)
        self._proxy = InstallationFilter(self)
        self._proxy.setSourceModel(self._model)

        self._build_ui()
        self._wire_shortcuts()
        self._model.set_rows(state.installations)
        self._installations = list(state.installations)

    # ------------------------------------------------------------- data sync
    def replace_rows(self, rows: list[Installation]) -> None:
        """Swap in the re-enumerated row set (pacman + flatpak + manual).

        `refresh_state.read` re-lists ALL providers (§83/§145/§276), so this
        replaces the previous snapshot wholesale. Keeping the old non-pacman
        rows (the old `others = …` merge) froze the boot-time Flatpak/Manual
        entries: a removed Flatpak app stayed listed forever, and every
        refresh doubled those rows. (Found by harness #3, QA M.)
        """
        self._installations = list(rows)
        self._model.set_rows(self._installations)

    # -------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._applications_tab(), "Applications")
        tabs.addTab(self._orphans_tab(), "Orphans")
        tabs.addTab(self._cleanup_tab(), "Cleanup")
        tabs.addTab(self._history_tab(), "History")
        self.setCentralWidget(tabs)
        self._tabs = tabs

    def _applications_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search applications…  (/)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._proxy.set_query)
        top.addWidget(self.search, 1)

        self.origin_filter = QComboBox()
        for value, label in _ORIGIN_CHOICES:
            self.origin_filter.addItem(label, value)
        self.origin_filter.currentIndexChanged.connect(
            lambda _i: self._proxy.set_origin_filter(self.origin_filter.currentData())
        )
        top.addWidget(self.origin_filter)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        vh = self.table.verticalHeader()
        if vh is not None:
            vh.setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.sortByColumn(4, Qt.SortOrder.DescendingOrder)
        sel_model = self.table.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_selection)
        splitter.addWidget(self.table)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.details = DetailsPanel()
        right_layout.addWidget(self.details, 1)
        self.uninstall_btn = QPushButton("Uninstall…")
        self.uninstall_btn.setProperty("danger", True)
        self.uninstall_btn.setEnabled(False)
        self.uninstall_btn.clicked.connect(self._uninstall_selected)
        right_layout.addWidget(self.uninstall_btn)
        splitter.addWidget(right)
        splitter.setSizes([560, 420])
        layout.addWidget(splitter, 1)
        return page

    def _orphans_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Orphan packages were installed as dependencies and are no longer "
            "required by any installed package. Review before removal — an "
            "orphan is not necessarily junk."
        )
        note.setWordWrap(True)
        note.setProperty("role", "subtitle")
        layout.addWidget(note)
        self.orphan_list = QListWidget()
        layout.addWidget(self.orphan_list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("Remove selected orphan…")
        btn.clicked.connect(self._remove_selected_orphan)
        row.addWidget(btn)
        layout.addLayout(row)
        return page

    def _cleanup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Scan an installed application for configuration, caches and data "
            "that CachyUninstall can attribute to it. Nothing is removed "
            "without your selection and confirmation."
        )
        note.setWordWrap(True)
        note.setProperty("role", "subtitle")
        layout.addWidget(note)

        row = QHBoxLayout()
        row.addWidget(QLabel("Application:"))
        self.cleanup_app = QComboBox()
        row.addWidget(self.cleanup_app, 1)
        scan = QPushButton("Scan for leftovers")
        scan.clicked.connect(self._scan_cleanup)
        row.addWidget(scan)
        layout.addLayout(row)

        self.cleanup_list = QListWidget()
        layout.addWidget(self.cleanup_list, 1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cleanup_run = QPushButton("Clean selected items…")
        self.cleanup_run.setEnabled(False)
        self.cleanup_run.clicked.connect(self._run_cleanup)
        btns.addWidget(self.cleanup_run)
        layout.addLayout(btns)
        self._cleanup_candidates: list[LeftoverCandidate] = []
        return page

    def _history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history_list = QListWidget()
        layout.addWidget(self.history_list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._reload_history)
        clear = QPushButton("Clear history")
        clear.clicked.connect(self._clear_history)
        row.addWidget(refresh)
        row.addWidget(clear)
        layout.addLayout(row)
        self._reload_history()
        return page

    def _wire_shortcuts(self) -> None:
        QShortcut(QKeySequence("/"), self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+R"), self, self._refresh_requested)
        delete = QAction(self)
        delete.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        delete.triggered.connect(self._uninstall_selected)
        self.addAction(delete)

    # --------------------------------------------------------------- actions
    def _focus_search(self) -> None:
        self._tabs.setCurrentIndex(0)
        self.search.setFocus()
        self.search.selectAll()

    def _refresh_requested(self) -> None:
        QMessageBox.information(
            self,
            "Refresh",
            "CachyUninstall re-reads the package database on every operation.\n"
            "Restart the application to fully rebuild the application list.",
        )

    def _on_selection(self) -> None:
        sel = self.table.selectionModel()
        if sel is None:
            return
        indexes = sel.selectedRows()
        if not indexes:
            self.details.show_package(None)
            self.uninstall_btn.setEnabled(False)
            return
        proxy_index = indexes[0]
        source_index = self._proxy.mapToSource(proxy_index)
        item = self._model.at(source_index.row())
        if item is None:
            return
        if item.provider is ProviderKind.PACMAN:
            record = next((p for p in self._state.packages if p.name == item.name), None)
            self.details.show_package(record)
            self.uninstall_btn.setEnabled(True)
        else:
            self.details.show_package(None)
            self.details.subtitle.setText(
                f"{item.display_name} is provided by {item.provider.value}; "
                "removal is offered through its own provider (see Cleanup for app data)."
            )
            if item.provider is ProviderKind.FLATPAK:
                self.uninstall_btn.setEnabled(True)
                return
            self.uninstall_btn.setEnabled(False)

    # ------------------------------------------------------------ uninstall
    def _selected_installation(self) -> Installation | None:
        sel = self.table.selectionModel()
        if sel is None:
            return None
        indexes = sel.selectedRows()
        if not indexes:
            return None
        src = self._proxy.mapToSource(indexes[0])
        return self._model.at(src.row())

    def _uninstall_selected(self) -> None:
        item = self._selected_installation()
        if item is None:
            return
        if item.provider is ProviderKind.FLATPAK:
            self._uninstall_flatpak(item)
            return
        if item.provider is not ProviderKind.PACMAN:
            self._info("Not removable", "This installation type is inspection-only in this release.")
            return
        name = PackageName(item.name)
        identity = self._state.identities.get(name, Identity(package=name))
        running = running_pids_for(identity)
        if running:
            answer = QMessageBox.question(
                self,
                "Application is running",
                f"{item.display_name} appears to be running ({len(running)} process(es)).\n\n"
                "Please close it first. Continue anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.uninstall_btn.setEnabled(False)
        Executor.run(
            lambda: self._prepare_pacman_plan(name),
            on_result=lambda payload: self._show_preview(item, payload),
            on_error=lambda err: self._failed("Analysis failed", err),
        )

    def _prepare_pacman_plan(self, name: PackageName) -> tuple[RemovalImpact, list[LeftoverCandidate], int]:
        session, oracle = _fresh_oracle()
        packages = session.packages()
        planner = RemovalPlanner(packages)
        impact = planner.analyze([name])
        identities = build_identity_index(packages)
        identity = identities.get(name, Identity(package=name))
        ctx = ScanContext(
            home=Path.home(),
            identity=identity,
            other_identities=tuple(i for k, i in identities.items() if k != name),
            oracle=oracle,
        )
        leftovers = LeftoverScanner(PathPolicy()).scan(ctx)
        generation = session.generation()
        return impact, leftovers, generation

    def _show_preview(
        self,
        item: Installation,
        payload: tuple[RemovalImpact, list[LeftoverCandidate], int],
    ) -> None:
        self.uninstall_btn.setEnabled(True)
        impact, leftovers, generation = payload
        dialog = PreviewDialog(item.display_name, impact, leftovers, self._state.settings, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        choice = dialog.choice()
        packages = self._state.packages
        planner = RemovalPlanner(packages)
        try:
            plan = planner.build_plan(
                [PackageName(item.name)],
                also_remove_new_orphans=choice.remove_orphan_deps,
                generation=generation,
                leftovers=tuple(choice.selected_leftovers),
            )
        except DependencyBlocked as exc:
            self._blocked(exc)
            return
        self._execute_plan(item, plan, choice)

    def _execute_plan(self, item: Installation, plan: RemovalPlan, choice: PreviewChoice) -> None:
        client = self._state.helper
        if not client.is_available():
            self._failed(
                "Privileged helper unavailable",
                "The CachyUninstall privileged service is not installed or not running.",
            )
            return

        progress = ProgressDialog(f"Removing {item.display_name}", self)
        client.connect_progress(progress.handle_event)
        progress.on_cancel(client.cancel_current)
        progress.show()

        self._state.history.journal_start(plan.plan_id, {"targets": list(map(str, plan.targets))})

        def done(reply: HelperReply) -> None:
            self._after_removal(item, plan, choice, reply, progress)

        client.remove_packages(plan, done)

    def _after_removal(
        self,
        item: Installation,
        plan: RemovalPlan,
        choice: PreviewChoice,
        reply: HelperReply,
        progress: ProgressDialog,
    ) -> None:
        progress.close()

        if not reply.ok:
            self._state.history.journal_finish(plan.plan_id, "failed")
            if reply.code == "authorization-denied":
                self._info("Authorization denied", "No changes were made.")
            else:
                self._failed("Removal failed", reply.message)
            return

        self._state.history.journal_finish(plan.plan_id, "done")
        self._state.history.record(
            HistoryKind.UNINSTALL,
            subject=item.name,
            provider="pacman",
            detail={"removed": list(map(str, reply.removed))},
            result="success",
        )
        # §276: after success the removed app must be gone from the list —
        # drop its rows now, not on restart.
        self._drop_removed_rows([str(n) for n in reply.removed])
        # state.packages is a snapshot: re-read the DB so the Orphans tab
        # drops the removed package and picks up packages that just became
        # orphans (§278), and details/cleanup views see current data.
        self.refresh_state()

        # Post-removal cleanup (user-side, validated again at execution).
        report: CleanupReport | None = None
        if choice.selected_leftovers:
            quarantine = Quarantine() if choice.use_quarantine else None
            report = CleanupExecutor(PathPolicy(), quarantine).execute(choice.selected_leftovers)
            self._state.history.record(
                HistoryKind.CLEANUP,
                subject=item.name,
                provider="local",
                detail={
                    "items": len(report.items),
                    "freed": report.freed_bytes,
                },
                result=report.kind.value,
            )
        # §276: the new history entry must be visible immediately.
        self._reload_history()
        self._show_result(item, reply, report)

    def _drop_removed_rows(self, removed: list[str]) -> None:
        """Remove uninstalled pacman rows from the table (in-memory only)."""
        gone = set(removed)
        self._installations = [
            row
            for row in self._installations
            if not (row.provider is ProviderKind.PACMAN and row.name in gone)
        ]
        self._model.set_rows(self._installations)
        self.table.clearSelection()
        self.details.show_package(None)
        self.uninstall_btn.setEnabled(False)

    def _show_result(
        self,
        item: Installation,
        reply: HelperReply,
        report: CleanupReport | None,
    ) -> None:
        lines = [f"{item.display_name} was removed.", ""]
        lines.append(f"Packages removed: {len(reply.removed)}")
        if report is not None:
            ok = [i for i in report.items if i.ok]
            lines.append(f"Leftover items cleaned: {len(ok)}")
            lines.append(f"Space reclaimed: {human_size(report.freed_bytes)}")
            failed = [i for i in report.items if not i.ok and i.error != "protected"]
            if failed:
                lines.append("")
                lines.append("Some items could not be removed:")
                lines.extend(f"• {i.path}: {i.error}" for i in failed)
        lines.append("")
        lines.append("Nothing else was modified.")
        QMessageBox.information(self, "Removal complete", "\n".join(lines))

    # -------------------------------------------------------------- orphans
    def refresh_state(self) -> None:
        """Background re-read of the package DB (phases §83/§145/§276/§278).

        Runs with FULL detail + origin resolution in a worker, then applies
        the new snapshot: rows, identities, package records and the Orphans
        tab. Used at startup (origin enrichment) and after every removal —
        filtering the old snapshot is not enough because `required_by` of
        other packages changes too (a dependency just lost its requirer).
        """

        Payload = tuple[list[Installation], list[PackageRecord], dict[PackageName, Identity]]
        flatpak = self._state.flatpak
        manual = ManualProvider()

        def read() -> Payload:
            session = AlpmSession()
            session.open()
            packages = session.packages(with_origin_resolution=True)
            identities = build_identity_index(packages)
            rows = PacmanProvider(session).list_installations(packages, identities)
            # The table also holds non-ALPM rows — boot merges them in
            # app.load(); dropping them here would make Flatpak/Manual
            # entries vanish at enrichment, Ctrl+R and post-removal refresh.
            rows += flatpak.list_installations()
            rows += manual.list_installations()
            return rows, packages, identities

        def apply(payload: Payload) -> None:
            rows, packages, identities = payload
            self._state.packages = packages
            self._state.identities = identities
            self.replace_rows(rows)
            self.load_orphans()

        Executor.run(read, apply, lambda err: LOG.warning("state refresh failed: %s", err))

    def load_orphans(self) -> None:
        self.orphan_list.clear()
        planner_pool = [p for p in self._state.packages if p.is_orphan_hint]
        for pkg in planner_pool:
            QListWidgetItem(
                f"{pkg.name}  ·  {human_size(pkg.size_bytes)}  ·  {pkg.description[:80]}",
                self.orphan_list,
            )

    def _remove_selected_orphan(self) -> None:
        row = self.orphan_list.currentItem()
        if row is None:
            return
        name = row.text().split("  ·")[0].strip()
        self._uninstall_by_name(name)

    def _uninstall_by_name(self, name: str) -> None:
        item = Installation(
            instance_id=f"pacman:{name}",
            provider=ProviderKind.PACMAN,
            name=name,
            display_name=name,
            version="",
            origin=Origin.FOREIGN,
            size_bytes=0,
        )
        Executor.run(
            lambda: self._prepare_pacman_plan(PackageName(name)),
            on_result=lambda payload: self._show_preview(item, payload),
            on_error=lambda err: self._failed("Analysis failed", err),
        )

    # -------------------------------------------------------------- cleanup
    def populate_cleanup_apps(self) -> None:
        self.cleanup_app.clear()
        for pkg in self._state.packages:
            self.cleanup_app.addItem(str(pkg.name), str(pkg.name))

    def _scan_cleanup(self) -> None:
        name = self.cleanup_app.currentData()
        if not name:
            return
        self.cleanup_run.setEnabled(False)
        Executor.run(
            lambda: self._scan_for(PackageName(name)),
            on_result=self._show_cleanup_scan,
            on_error=lambda err: self._failed("Scan failed", err),
        )

    def _scan_for(self, name: PackageName) -> list[LeftoverCandidate]:
        _session, oracle = _fresh_oracle()
        identity = self._state.identities.get(name, Identity(package=name))
        ctx = ScanContext(
            home=Path.home(),
            identity=identity,
            other_identities=tuple(i for k, i in self._state.identities.items() if k != name),
            oracle=oracle,
        )
        return LeftoverScanner(PathPolicy()).scan(ctx)

    def _show_cleanup_scan(self, candidates: list[LeftoverCandidate]) -> None:
        self._cleanup_candidates = candidates
        self.cleanup_list.clear()
        eligible = [
            c
            for c in candidates
            if c.confidence is not Confidence.PROTECTED
            and (self._state.settings.show_low_confidence or c.confidence is not Confidence.LOW)
        ]
        for cand in eligible:
            item = QListWidgetItem(
                f"{cand.path}   ·   {human_size(cand.size_bytes)}   ·   {cand.confidence.value}"
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip(cand.reason)
            self.cleanup_list.addItem(item)
        for cand in candidates:
            if cand.confidence is Confidence.PROTECTED:
                # reason already starts with "Protected:" — no decoration
                QListWidgetItem(f"{cand.path} — {cand.reason}", self.cleanup_list)
        self.cleanup_run.setEnabled(bool(eligible))

    def _run_cleanup(self) -> None:
        selected: list[LeftoverCandidate] = []
        eligible = [c for c in self._cleanup_candidates if c.confidence is not Confidence.PROTECTED]
        for i in range(self.cleanup_list.count()):
            row_item = self.cleanup_list.item(i)
            if row_item is not None and i < len(eligible) and row_item.checkState() == Qt.CheckState.Checked:
                selected.append(eligible[i])
        if not selected:
            return
        mode = (
            "They will be moved to quarantine."
            if self._state.settings.use_quarantine
            else "This is permanent."
        )
        answer = QMessageBox.question(self, "Confirm cleanup", f"Remove {len(selected)} item(s)? {mode}")
        if answer != QMessageBox.StandardButton.Yes:
            return
        Executor.run(
            lambda: CleanupExecutor(
                PathPolicy(),
                Quarantine() if self._state.settings.use_quarantine else None,
            ).execute(selected),
            on_result=self._cleanup_done,
            on_error=lambda err: self._failed("Cleanup failed", err),
        )

    def _cleanup_done(self, report: CleanupReport) -> None:
        ok = [i for i in report.items if i.ok]
        failed = [i for i in report.items if not i.ok]
        QMessageBox.information(
            self,
            "Cleanup finished",
            f"Removed {len(ok)} item(s), freed {human_size(report.freed_bytes)}."
            + (f"\n{len(failed)} could not be removed (see details in log)." if failed else ""),
        )

    # ------------------------------------------------------------------ misc
    def _uninstall_flatpak(self, item: Installation) -> None:
        """Flatpak removal via the provider's own CLI (D17).

        flatpak performs its own authentication for system-scope installations;
        user-scope uninstall is unprivileged. '--delete-data' also removes
        ~/.var/app/<id> through Flatpak's own tracking.
        """
        if not self._state.flatpak.is_available():
            self._info("Flatpak unavailable", "The flatpak command is not installed.")
            return
        scope = "system" if ":system:" in item.instance_id else "user"
        answer = QMessageBox.question(
            self,
            f"Remove {item.display_name}",
            f"This will run Flatpak's own removal for {item.name} ({scope} scope),\n"
            "including its application data (--delete-data).\n\nContinue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def do_remove() -> str:
            self._state.flatpak.uninstall(item.name, scope)
            return "ok"

        def succeeded(_result: object) -> None:
            self._state.history.record(
                HistoryKind.UNINSTALL,
                subject=item.name,
                provider="flatpak",
                detail={"scope": scope},
                result="success",
            )
            # Same post-removal acceptance as the pacman path (D19/§276):
            # the removed installation must not stay listed.
            self.refresh_state()
            self._info(
                "Removed",
                f"{item.display_name} was removed by Flatpak, including its app data.",
            )

        Executor.run(do_remove, succeeded, lambda err: self._failed("Flatpak removal failed", err))

    def _reload_history(self) -> None:
        self.history_list.clear()
        for entry in self._state.history.entries():
            QListWidgetItem(
                f"{entry.action} · {entry.subject} · {entry.provider} · {entry.result}",
                self.history_list,
            )

    def _clear_history(self) -> None:
        self._state.history.clear()
        self._reload_history()

    def _blocked(self, exc: DependencyBlocked) -> None:
        QMessageBox.warning(
            self,
            "Cannot uninstall",
            "Other installed packages require this one:\n\n"
            + "\n".join(f"• {b}" for b in exc.blockers)
            + "\n\nNo changes were made.",
        )

    def _failed(self, title: str, detail: str) -> None:
        self.uninstall_btn.setEnabled(True)
        QMessageBox.critical(self, title, detail)

    def _info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

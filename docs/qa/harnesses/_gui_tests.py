"""TEMPORARY physical GUI acceptance harness (QA A/C/N + screenshots).

Runs the real MainWindow offscreen (QT_QPA_PLATFORM=offscreen) against the
live package DB inside the disposable container and drives it through:

  boot -> enrichment -> keyboard '/' -> search -> details vs pacman -Qi ->
  tab screenshots -> Delete-key preview -> cancel (no side effects) ->
  real E2E removal of konsole (preview -> leftovers selected -> polkit ->
  progress -> result box -> table/history refresh -> quarantine -> history)

Every step prints PASS/FAIL; exit code = number of failures.
Screenshots land in docs/screenshots/ (candidates for metainfo).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QMessageBox,
)

from cachyuninstall import APP_ID
from cachyuninstall.app import _start_enrichment
from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.filesystem import Quarantine
from cachyuninstall.persistence.history import HistoryStore
from cachyuninstall.persistence.settings import load_settings
from cachyuninstall.privilege.client import HelperClient
from cachyuninstall.providers.flatpak import FlatpakProvider
from cachyuninstall.providers.manual import ManualProvider
from cachyuninstall.providers.pacman import PacmanProvider
from cachyuninstall.ui.main_window import AppState, MainWindow
from cachyuninstall.ui.preview_dialog import PreviewDialog
from cachyuninstall.ui.progress_dialog import ProgressDialog
from cachyuninstall.ui.theme import LIGHT, stylesheet
from cachyuninstall.ui.workers import Executor  # noqa: F401  (needed for QThreadPool)

SHOTS = Path(__file__).resolve().parents[3] / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []
TARGET = "konsole"
S: dict[str, Any] = {}


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""), flush=True)


def sh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def installed(name: str) -> bool:
    return sh(["pacman", "-Q", name]).returncode == 0


def later(ms: int, fn) -> None:
    QTimer.singleShot(ms, fn)


def pump_until(cond, timeout_s: float, on_ok, on_fail, interval_ms: int = 120) -> None:
    deadline = time.monotonic() + timeout_s

    def tick() -> None:
        try:
            result = cond()
        except Exception as exc:  # harness must never hang on a bad condition
            on_fail(f"condition error: {exc}")
            return
        if result:
            on_ok(result)
        elif time.monotonic() > deadline:
            on_fail(f"timeout after {timeout_s}s")
        else:
            later(interval_ms, tick)

    tick()


def grab(widget: Any, name: str) -> None:
    pm = widget.grab()
    path = SHOTS / name
    pm.save(str(path))
    size = path.stat().st_size if path.exists() else 0
    print(f"  shot {name}: {size} bytes", flush=True)


def find_dialog(cls):
    def inner():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, cls) and w.isVisible():
                return w
        return None

    return inner


def pacman_depends(name: str) -> list[str]:
    out = sh(["pacman", "-Qi", name]).stdout
    m = re.search(r"^Depends On\s*:\s*(.+)$", out, re.MULTILINE)
    if not m or m.group(1).strip() == "None":
        return []
    return m.group(1).split()


def base_token(tok: str) -> str:
    return re.split(r"[<>=]", tok, maxsplit=1)[0].strip()


def fail_all(reason: str) -> None:
    check("GUI flow aborted", False, reason)
    finish()


# -------------------------------------------------------------------- boot
def main() -> int:
    QApplication.setApplicationName(APP_ID)
    QApplication.setOrganizationName("CachyOS")
    app = QApplication([])

    settings = load_settings()
    app.setStyleSheet(stylesheet(LIGHT))

    check("GUI-00 target installed before E2E", installed(TARGET), TARGET)
    # only dependencies that are ACTUALLY installed may be required to survive
    S["deps_installed_before"] = [d for d in map(base_token, pacman_depends(TARGET)) if installed(d)]
    S["config_dir"] = Path.home() / ".config" / TARGET
    S["data_dir"] = Path.home() / ".local" / "share" / TARGET
    check(
        "GUI-00b seeded leftovers exist",
        bool(S["config_dir"].exists() and S["data_dir"].exists()),
        f"{S['config_dir']}, {S['data_dir']}",
    )

    session = AlpmSession()
    session.open()
    packages = session.packages(with_origin_resolution=False, full_detail=False)
    pacman = PacmanProvider(session)
    installations = pacman.list_installations_light(packages)
    flatpak = FlatpakProvider()
    manual = ManualProvider()
    installations += flatpak.list_installations()
    installations += manual.list_installations()
    state = AppState(
        session=session,
        packages=packages,
        identities={},
        settings=settings,
        history=HistoryStore(),
        helper=HelperClient(),
        flatpak=flatpak,
        installations=installations,
    )

    window = MainWindow(state)
    window.resize(1366, 768)
    window.show()
    window.activateWindow()
    window.load_orphans()
    window.populate_cleanup_apps()
    _start_enrichment(window)
    S["window"] = window
    S["app"] = app
    S["history_before"] = len(state.history.entries())
    print(f"boot ok; history entries at boot: {S['history_before']}", flush=True)

    pump_until(
        lambda: bool(window._state.identities),
        150,
        lambda _r: step_geometry(),
        lambda why: fail_all(f"enrichment never finished ({why})"),
        interval_ms=300,
    )
    return app.exec()


# ------------------------------------------------------------------- steps
def step_geometry() -> None:
    w: MainWindow = S["window"]
    check("GUI-01 enrichment completed", True, f"{len(w._state.identities)} identities")
    usable = (
        w.width() >= 1300
        and w.height() >= 700
        and w.table.isVisible()
        and w.details.isVisible()
        and w.uninstall_btn.isVisible()
    )
    check("GUI-02 window geometry 1366x768 usable", usable, f"{w.width()}x{w.height()}")
    grab(w, "01-main-window.png")
    check("GUI-03 screenshot main window", (SHOTS / "01-main-window.png").stat().st_size > 5000)

    w.table.setFocus()
    QTest.keyClick(w, Qt.Key.Key_Slash)
    focused = QApplication.focusWidget()
    check(
        "GUI-04 keyboard '/' focuses search",
        focused is w.search,
        type(focused).__name__ if focused else "none",
    )
    step_search()


def step_search() -> None:
    w: MainWindow = S["window"]
    w.search.setText(TARGET)
    rows = w._proxy.rowCount()
    check("GUI-05 search filters list", rows == 1, f"rows={rows} for '{TARGET}'")
    w.table.selectRow(0)
    title = w.details.title.text()
    labels = [lbl.text() for lbl in w.details.form_widget.findChildren(QLabel)]
    pacman_version = ""
    for line in sh(["pacman", "-Qi", TARGET]).stdout.splitlines():
        if line.startswith("Version"):
            pacman_version = line.split(":", 1)[1].strip()
    check(
        "GUI-06 details metadata matches pacman -Qi",
        title != "Select an application" and pacman_version in labels,
        f"title={title!r} version-shown={pacman_version in labels} ({pacman_version})",
    )
    grab(w, "02-search-details.png")
    check("GUI-07 screenshot search+details", (SHOTS / "02-search-details.png").stat().st_size > 5000)
    step_tabs(0)


def step_tabs(idx: int) -> None:
    w: MainWindow = S["window"]
    shots = {1: "03-orphans-tab.png", 2: "04-cleanup-tab.png", 3: "05-history-tab.png"}
    w._tabs.setCurrentIndex(idx)
    if idx in shots:
        later(250, lambda i=idx: _shot_tab(i))
        return
    if idx < 3:
        later(250, lambda i=idx: step_tabs(i + 1))
        return
    count = w.history_list.count()
    check(
        "GUI-08 history tab shows prior entries",
        count >= int(S["history_before"]),
        f"{count} shown, {S['history_before']} recorded",
    )
    step_preview_cancel()


def _shot_tab(idx: int) -> None:
    w: MainWindow = S["window"]
    name = {1: "03-orphans-tab.png", 2: "04-cleanup-tab.png", 3: "05-history-tab.png"}[idx]
    grab(w, name)
    check(f"GUI screenshot tab {idx} ({name})", (SHOTS / name).stat().st_size > 3000)
    later(100, lambda i=idx: step_tabs(i + 1))


def step_preview_cancel() -> None:
    w: MainWindow = S["window"]
    w._tabs.setCurrentIndex(0)
    w.search.setText(TARGET)
    later(200, _fire_delete_key)


def _fire_delete_key() -> None:
    w: MainWindow = S["window"]
    w.table.setFocus()
    w.table.selectRow(0)
    QTest.keyClick(w.table, Qt.Key.Key_Delete)
    pump_until(
        find_dialog(PreviewDialog),
        90,
        on_preview_first,
        lambda why: fail_all(f"preview did not appear after Delete key: {why}"),
    )


def on_preview_first(dialog: PreviewDialog) -> None:
    check("GUI-10 preview dialog opened via Delete key", True, dialog.windowTitle())
    grab(dialog, "06-preview-dialog.png")
    check("GUI-11 screenshot preview", (SHOTS / "06-preview-dialog.png").stat().st_size > 4000)

    titles = [g.title() for g in dialog.findChildren(QGroupBox)]
    check(
        "GUI-12 preview sections present",
        any(t.startswith("Packages to remove") for t in titles)
        and any(t.startswith("Application data") for t in titles),
        " | ".join(titles),
    )

    boxes: list[tuple[QCheckBox, Any]] = list(dialog._checkboxes)
    check("GUI-13 leftover candidates listed", len(boxes) >= 2, f"{len(boxes)} candidates")
    preselected = [b for b, _ in boxes if b.isChecked()]
    check(
        "GUI-14 D9 defaults: no leftover preselected (config kept)",
        not preselected,
        f"{len(preselected)}/{len(boxes)} preselected",
    )
    check("GUI-15 quarantine default ON", dialog.chk_quarantine.isChecked())
    orphans = dialog.chk_orphans
    S["orphans_default_checked"] = bool(orphans is not None and orphans.isChecked())
    check(
        "GUI-15b orphan cascade opt-in default OFF",
        not S["orphans_default_checked"],
        f"offered={orphans is not None}",
    )

    S["hist_before_cancel"] = len(S["window"]._state.history.entries())
    dialog.reject()
    later(700, verify_cancel_side_effects)


def verify_cancel_side_effects() -> None:
    w: MainWindow = S["window"]
    check("GUI-16 cancel: target still installed", installed(TARGET))
    hist_after = len(w._state.history.entries())
    check(
        "GUI-17 cancel: no history entry added",
        hist_after == S["hist_before_cancel"],
        f"{S['hist_before_cancel']} -> {hist_after}",
    )
    no_dialogs = not any(
        isinstance(x, (PreviewDialog, ProgressDialog, QMessageBox)) and x.isVisible()
        for x in QApplication.topLevelWidgets()
    )
    check("GUI-18 cancel: no dialogs left open", no_dialogs)
    step_e2e_preview()


def step_e2e_preview() -> None:
    w: MainWindow = S["window"]
    check("GUI-19 Uninstall button re-enabled after cancel", w.uninstall_btn.isEnabled())
    # spy on ProgressDialog construction so a fast removal cannot dodge it
    created: list[ProgressDialog] = []
    orig_init = ProgressDialog.__init__

    def spy(self: ProgressDialog, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        created.append(self)

    ProgressDialog.__init__ = spy  # type: ignore[method-assign]
    S["progress_created"] = created
    w.uninstall_btn.click()
    pump_until(
        find_dialog(PreviewDialog),
        90,
        on_preview_second,
        lambda why: fail_all(f"E2E preview did not appear: {why}"),
    )


def on_preview_second(dialog: PreviewDialog) -> None:
    boxes = list(dialog._checkboxes)
    for b, _c in boxes:
        b.setChecked(True)
    S["selected_leftovers"] = len(boxes)
    box = dialog.findChild(QDialogButtonBox)
    ok = box.button(QDialogButtonBox.StandardButton.Ok)
    grab(dialog, "06b-preview-selected.png")
    ok.click()  # accept -> real removal flow starts after the dialog loop unwinds
    pump_until(lambda: bool(S["progress_created"]) or find_dialog(QMessageBox)(), 60, on_progress_started, lambda why: on_no_progress(why))


def on_progress_started(_r: Any) -> None:
    created: list[ProgressDialog] = S["progress_created"]
    if created:
        S["progress"] = created[0]
        grab(created[0], "07-progress-dialog.png")
        check("GUI-20 progress dialog created", True)
    pump_until(find_dialog(QMessageBox), 120, on_result_box, on_e2e_fail)


def on_no_progress(why: str) -> None:
    check("GUI-20 progress dialog created", False, why)
    pump_until(find_dialog(QMessageBox), 120, on_result_box, on_e2e_fail)


def on_e2e_fail(why: str) -> None:
    check("GUI E21 result box appeared", False, why)
    finish()


def on_result_box(box: QMessageBox) -> None:
    text = box.text()
    S["result_text"] = text
    grab(box, "08-removal-complete.png")
    check(
        "GUI-21 result box 'Removal complete'",
        box.windowTitle() == "Removal complete" and "was removed" in text,
        text.replace("\n", " / ")[:180],
    )
    # real progress events evidence (stage text beyond the initial placeholder)
    progress: ProgressDialog | None = S.get("progress")
    if progress is not None:
        status = progress.status.text()
        check(
            "GUI-20b progress received REAL events",
            status != "Preparing…" and status != "",
            f"final status={status!r} bar={progress.bar.value()}",
        )
    box.reject()
    later(600, verify_post_state)


def verify_post_state() -> None:
    w: MainWindow = S["window"]
    check("GUI-22 pacman agrees: target gone", not installed(TARGET))
    check("GUI-23 target binary gone", not Path(f"/usr/bin/{TARGET}").exists())

    w.search.setText(TARGET)
    rows = w._proxy.rowCount()
    check("GUI-24 app gone from list (table refreshed)", rows == 0, f"rows={rows}")
    w.search.clear()

    cfg: Path = S["config_dir"]
    data: Path = S["data_dir"]
    entries = Quarantine().list_entries()
    qpaths = [e.original_path for e in entries]
    check(
        "GUI-25 leftovers moved to quarantine",
        (not cfg.exists() and not data.exists() and any(str(cfg) in p for p in qpaths)),
        f"cfg_exists={cfg.exists()} data_exists={data.exists()} q_entries={qpaths}",
    )
    check(
        "GUI-26 result box reported cleanup",
        "Leftover items cleaned" in str(S.get("result_text", "")),
        str(S.get("result_text", ""))[:180],
    )

    hist = [(e.action, e.subject, e.result) for e in w._state.history.entries()]
    check(
        "GUI-27 history has successful uninstall entry",
        ("uninstall", TARGET, "success") in hist,
        str(hist[:4]),
    )
    check(
        "GUI-28 history has cleanup entry",
        ("cleanup", TARGET, "success") in hist,
        str(hist[:4]),
    )
    w._tabs.setCurrentIndex(3)
    later(300, verify_history_tab)


def verify_history_tab() -> None:
    w: MainWindow = S["window"]
    texts = [w.history_list.item(i).text() for i in range(w.history_list.count())]
    check(
        "GUI-29 history tab visibly shows new entry",
        any(TARGET in t for t in texts),
        f"{len(texts)} rows; first={texts[0][:80] if texts else ''}",
    )
    before: list[str] = S["deps_installed_before"]
    gone = [d for d in before if not installed(d)]
    check(
        "GUI-30 direct dependencies NOT removed (no silent cascade)",
        not gone,
        f"gone={gone} survived={len(before) - len(gone)}/{len(before)}",
    )
    jr = sh(["journalctl", "-u", "cachyuninstall-helper", "--since", "-45 min", "--no-pager"])
    tb = [ln for ln in jr.stdout.splitlines() if "Traceback" in ln or "TypeError" in ln]
    check("GUI-31 helper journal clean during GUI flow", not tb, tb[0] if tb else "")
    finish()


def finish() -> None:
    if any(r[0] == "__finished__" for r in RESULTS):
        return
    RESULTS.append(("__finished__", True, ""))
    fails = [r for r in RESULTS if not r[1]]
    print("\n=== GUI ACCEPTANCE SUMMARY ===", flush=True)
    print(f"{len(RESULTS) - 1} checks, {len(fails)} failed", flush=True)
    for label, ok, detail in fails:
        print(f"  FAIL: {label} — {detail}", flush=True)
    (SHOTS / "gui-qa-results.json").write_text(
        json.dumps(
            [{"check": l, "ok": o, "detail": d} for l, o, d in RESULTS if l != "__finished__"],
            indent=2,
        )
    )
    app: QApplication = S["app"]
    QTimer.singleShot(0, lambda: app.exit(len(fails)))


if __name__ == "__main__":
    raise SystemExit(main())

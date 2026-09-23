"""TEMPORARY physical harness #2 — QA C (orphans, §278) + keyboard (§N).

Continues from harness #1 (which removed konsole and thereby created the
orphans seen here). Drives the real MainWindow offscreen:

  boot -> enrichment -> orphan tab correctness (vs full-detail + CLI) ->
  keyboard: arrows, '/', Ctrl+R -> orphan preview via tab button ->
  Esc cancels without side effects -> physical orphan removal (gspell)
  -> pacman agrees, table + orphan tab + history refreshed, deps survive.

PASS/FAIL per check; exit code = number of failures.
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
    QDialogButtonBox,
    QGroupBox,
    QMessageBox,
    QPushButton,
)

from cachyuninstall import APP_ID
from cachyuninstall.app import _start_enrichment
from cachyuninstall.core.alpm_session import AlpmSession
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

SHOTS = Path(__file__).resolve().parents[3] / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []
TARGET = "gspell"
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
        except Exception as exc:
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
    path = SHOTS / name
    widget.grab().save(str(path))
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


def orphan_names(w: MainWindow) -> list[str]:
    return [w.orphan_list.item(i).text().split("  ·")[0].strip() for i in range(w.orphan_list.count())]


def fail_all(reason: str) -> None:
    check("harness aborted", False, reason)
    finish()


def main() -> int:
    QApplication.setApplicationName(APP_ID)
    QApplication.setOrganizationName("CachyOS")
    app = QApplication([])
    app.setStyleSheet(stylesheet(LIGHT))

    check("ORP-00 target installed", installed(TARGET), TARGET)
    S["deps_installed_before"] = [d for d in map(base_token, pacman_depends(TARGET)) if installed(d)]
    S["history_before"] = len(HistoryStore().entries())

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
        settings=settings_load(),
        history=HistoryStore(),
        helper=HelperClient(),
        flatpak=flatpak,
        installations=installations,
    )

    window = MainWindow(state)
    window.resize(1366, 768)
    window.show()
    window.activateWindow()
    # mirrors app.run_gui: NO load_orphans at boot (light data), enrichment
    # fills the orphan tab.
    window.populate_cleanup_apps()
    _start_enrichment(window)
    S["window"] = window
    S["app"] = app
    print("boot ok", flush=True)

    pump_until(
        lambda: bool(window._state.identities),
        150,
        lambda _r: step_orphan_tab(),
        lambda why: fail_all(f"enrichment never finished ({why})"),
        interval_ms=300,
    )
    return app.exec()


def settings_load():
    from cachyuninstall.persistence.settings import load_settings

    return load_settings()


# ------------------------------------------------------------------- steps
def step_orphan_tab() -> None:
    w: MainWindow = S["window"]
    tab_names = orphan_names(w)
    full_count = sum(1 for p in w._state.packages if p.is_orphan_hint)
    cli_count = len([ln for ln in sh(["cachyuninstall", "--orphans"]).stdout.splitlines() if ln.strip()])
    check(
        "ORP-01 orphan tab matches full-detail computation",
        len(tab_names) == full_count,
        f"tab={len(tab_names)} full={full_count}",
    )
    check(
        "ORP-02 orphan tab matches CLI cross-check",
        len(tab_names) == cli_count,
        f"tab={len(tab_names)} cli={cli_count} names={tab_names}",
    )
    check("ORP-03 target listed as orphan", TARGET in tab_names, str(tab_names))
    w._tabs.setCurrentIndex(1)
    later(300, _shot_orphan_tab)


def _shot_orphan_tab() -> None:
    w: MainWindow = S["window"]
    grab(w, "09-orphans-tab.png")
    check("ORP-04 screenshot orphan tab", (SHOTS / "09-orphans-tab.png").stat().st_size > 3000)
    step_keyboard()


def step_keyboard() -> None:
    w: MainWindow = S["window"]
    w._tabs.setCurrentIndex(0)
    w.table.setFocus()
    w.table.selectRow(0)
    before = w.table.currentIndex().row()
    QTest.keyClick(w.table, Qt.Key.Key_Down)
    after = w.table.currentIndex().row()
    check("KBD-01 arrow Down moves selection", after != before, f"{before} -> {after}")
    QTest.keyClick(w.table, Qt.Key.Key_Up)
    check(
        "KBD-02 details populated for arrow selection",
        w.details.title.text() not in ("", "Select an application"),
        w.details.title.text(),
    )
    w.table.setFocus()
    QTest.keyClick(w, Qt.Key.Key_Slash)
    check("KBD-03 '/' focuses search", QApplication.focusWidget() is w.search)
    w.search.clear()

    # Ctrl+R shows the Refresh note. Schedule the pump BEFORE the keystroke:
    # the shortcut handler opens a modal box synchronously inside keyClick,
    # and its nested loop is what processes our timers.
    pump_until(find_dialog(QMessageBox), 10, _on_ctrl_r, lambda why: fail_all(f"Ctrl+R box missing: {why}"))
    QTest.keyClick(w, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)


def _on_ctrl_r(box: QMessageBox) -> None:
    check("KBD-04 Ctrl+R opens Refresh note", box.windowTitle() == "Refresh", box.windowTitle())
    grab(box, "10-ctrl-r-info.png")
    box.reject()
    later(400, step_orphan_preview)


def step_orphan_preview() -> None:
    w: MainWindow = S["window"]
    w._tabs.setCurrentIndex(1)
    later(200, _select_orphan)


def _select_orphan() -> None:
    w: MainWindow = S["window"]
    names = orphan_names(w)
    if TARGET not in names:
        fail_all(f"{TARGET} not in orphan tab: {names}")
        return
    w.orphan_list.setCurrentRow(names.index(TARGET))
    btns = [b for b in w.findChildren(QPushButton) if "Remove selected orphan" in b.text()]
    if not btns:
        fail_all("orphan remove button not found")
        return
    S["orphan_btn"] = btns[0]
    btns[0].click()  # physical path: Orphans tab -> button -> preview
    pump_until(find_dialog(PreviewDialog), 90, _on_orphan_preview, lambda why: fail_all(f"orphan preview missing: {why}"))


def _on_orphan_preview(dialog: PreviewDialog) -> None:
    check("ORP-05 preview opens for orphan", TARGET in dialog.windowTitle(), dialog.windowTitle())
    grab(dialog, "11-orphan-preview.png")
    titles = [g.title() for g in dialog.findChildren(QGroupBox)]
    check(
        "ORP-06 preview sections present",
        any(t.startswith("Packages to remove") for t in titles),
        " | ".join(titles),
    )
    orphans_box = dialog.chk_orphans
    check(
        "ORP-07 orphan cascade opt-in default OFF",
        not (orphans_box is not None and orphans_box.isChecked()),
        f"offered={orphans_box is not None}",
    )
    # Esc closes without side effects
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    pump_until(lambda: find_dialog(PreviewDialog)() is None, 10, _on_esc_closed, lambda why: fail_all(f"Esc did not close preview: {why}"))


def _on_esc_closed(_r: Any) -> None:
    w: MainWindow = S["window"]
    check("ORP-08 Esc closed preview", True)
    check("ORP-09 cancel: target still installed", installed(TARGET))
    hist = len(w._state.history.entries())
    check("ORP-10 cancel: no history entry", hist == S["history_before"], f"{S['history_before']} -> {hist}")
    no_dialogs = not any(
        isinstance(x, (PreviewDialog, QMessageBox)) and x.isVisible() for x in QApplication.topLevelWidgets()
    )
    check("ORP-11 cancel: no dialogs left open", no_dialogs)
    later(300, _second_attempt)


def _second_attempt() -> None:
    w: MainWindow = S["window"]
    names = orphan_names(w)
    w.orphan_list.setCurrentRow(names.index(TARGET))
    # spy on ProgressDialog so a fast run cannot dodge the evidence
    created: list[ProgressDialog] = []
    orig_init = ProgressDialog.__init__

    def spy(self: ProgressDialog, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        created.append(self)

    ProgressDialog.__init__ = spy  # type: ignore[method-assign]
    S["progress_created"] = created
    S["orphan_btn"].click()
    pump_until(find_dialog(PreviewDialog), 90, _on_accept_preview, lambda why: fail_all(f"2nd preview missing: {why}"))


def _on_accept_preview(dialog: PreviewDialog) -> None:
    box = dialog.findChild(QDialogButtonBox)
    ok = box.button(QDialogButtonBox.StandardButton.Ok)
    ok.click()
    pump_until(
        lambda: bool(S["progress_created"]) or find_dialog(QMessageBox)(),
        60,
        _on_progress_started,
        lambda why: fail_all(f"progress/result missing: {why}"),
    )


def _on_progress_started(_r: Any) -> None:
    created: list[ProgressDialog] = S["progress_created"]
    if created:
        grab(created[0], "12-progress-dialog.png")
        check("ORP-12 progress dialog created", True)
    pump_until(find_dialog(QMessageBox), 120, _on_result_box, lambda why: fail_all(f"result box missing: {why}"))


def _on_result_box(box: QMessageBox) -> None:
    text = box.text()
    check(
        "ORP-13 result box reports removal",
        box.windowTitle() == "Removal complete" and f"{TARGET} was removed" in text,
        text.replace("\n", " / ")[:160],
    )
    grab(box, "13-removal-complete.png")
    created: list[ProgressDialog] = S.get("progress_created", [])
    if created:
        status = created[0].status.text()
        check(
            "ORP-14 progress received REAL events",
            status not in ("", "Preparing…"),
            f"final status={status!r} bar={created[0].bar.value()}",
        )
    box.reject()
    later(600, _verify_post)


def _verify_post() -> None:
    w: MainWindow = S["window"]
    check("ORP-15 pacman agrees: orphan gone", not installed(TARGET))

    w._tabs.setCurrentIndex(0)
    w.search.setText(TARGET)
    rows = w._proxy.rowCount()
    check("ORP-16 removed row gone from applications list", rows == 0, f"rows={rows}")
    w.search.clear()

    w._tabs.setCurrentIndex(1)
    # the orphan tab is refreshed asynchronously (state re-read in a worker):
    pump_until(
        lambda: TARGET not in orphan_names(S["window"]),
        30,
        lambda _r: _verify_orphan_tab(),
        lambda why: fail_all(f"orphan tab never refreshed ({why})"),
        interval_ms=250,
    )


def _verify_orphan_tab() -> None:
    w: MainWindow = S["window"]
    names = orphan_names(w)
    cli_lines = [ln for ln in sh(["cachyuninstall", "--orphans"]).stdout.splitlines() if ln.strip()]
    cli = [ln.split()[1] for ln in cli_lines if len(ln.split()) >= 2]  # "origin name version"
    check("ORP-17 orphan tab refreshed: target gone", TARGET not in names, str(names))
    check(
        "ORP-18 orphan tab matches fresh CLI after removal",
        sorted(names) == sorted(cli),
        f"tab={sorted(names)} cli={sorted(cli)}",
    )

    before: list[str] = S["deps_installed_before"]
    gone = [d for d in before if not installed(d)]
    check(
        "ORP-19 direct deps NOT removed (no silent cascade)",
        not gone,
        f"gone={gone} survived={len(before) - len(gone)}/{len(before)}",
    )

    hist = [(e.action, e.subject, e.result) for e in w._state.history.entries()]
    check("ORP-20 history has successful uninstall entry", ("uninstall", TARGET, "success") in hist, str(hist[:3]))
    w._tabs.setCurrentIndex(3)
    later(300, _verify_history_tab)


def _verify_history_tab() -> None:
    w: MainWindow = S["window"]
    texts = [w.history_list.item(i).text() for i in range(w.history_list.count())]
    check("ORP-21 history tab visibly shows new entry", any(TARGET in t for t in texts), f"{len(texts)} rows")
    jr = sh(["journalctl", "-u", "cachyuninstall-helper", "--since", "-30 min", "--no-pager"])
    tb = [ln for ln in jr.stdout.splitlines() if "Traceback" in ln or "TypeError" in ln]
    check("ORP-22 helper journal clean", not tb, tb[0] if tb else "")
    finish()


def finish() -> None:
    if any(r[0] == "__finished__" for r in RESULTS):
        return
    RESULTS.append(("__finished__", True, ""))
    fails = [r for r in RESULTS if not r[1]]
    print("\n=== ORPHAN + KEYBOARD ACCEPTANCE SUMMARY ===", flush=True)
    print(f"{len(RESULTS) - 1} checks, {len(fails)} failed", flush=True)
    for label, _ok, detail in fails:
        print(f"  FAIL: {label} — {detail}", flush=True)
    (SHOTS / "gui-qa2-results.json").write_text(
        json.dumps(
            [{"check": l, "ok": o, "detail": d} for l, o, d in RESULTS if l != "__finished__"],
            indent=2,
        )
    )
    app: QApplication = S["app"]
    QTimer.singleShot(0, lambda: app.exit(len(fails)))


if __name__ == "__main__":
    raise SystemExit(main())

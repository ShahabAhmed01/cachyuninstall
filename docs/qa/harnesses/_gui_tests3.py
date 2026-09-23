"""TEMPORARY physical harness #3 — QA M (Flatpak, §289).

Preconditions (set up outside the harness):
  * org.gnome.Calculator installed in the SYSTEM scope
  * org.gnome.Calculator installed in the USER scope (--no-related)
  * both visible to `flatpak list --app`

Drives the real MainWindow offscreen:

  boot -> enrichment keeps BOTH flatpak rows (refresh_state merge) ->
  origin=Flatpak -> select SYSTEM row -> confirm box names the scope ->
  removal succeeds while BOTH scopes exist (the ambiguity case) ->
  user row survives, --delete-data removed ~/.var/app, history recorded ->
  table refreshed without the removed row -> same cycle for the USER row ->
  nothing left in either scope, pacman DB untouched.

PASS/FAIL per check; exit code = number of failures.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThreadPool, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from cachyuninstall import APP_ID
from cachyuninstall.app import _start_enrichment
from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.models import Origin
from cachyuninstall.persistence.history import HistoryStore
from cachyuninstall.persistence.settings import load_settings
from cachyuninstall.privilege.client import HelperClient
from cachyuninstall.providers.flatpak import FlatpakProvider
from cachyuninstall.providers.manual import ManualProvider
from cachyuninstall.providers.pacman import PacmanProvider
from cachyuninstall.ui.main_window import AppState, MainWindow
from cachyuninstall.ui.theme import LIGHT, stylesheet

SHOTS = Path(__file__).resolve().parents[3] / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []
APP = "org.gnome.Calculator"
SYS_ID = f"flatpak:system:{APP}"
USR_ID = f"flatpak:user:{APP}"
DATA_DIR = Path.home() / ".var" / "app" / APP
S: dict[str, Any] = {}


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""), flush=True)


def sh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _instrument_executor() -> None:
    """Trace Executor submissions/read/apply/errors — refresh delivery debug."""
    from cachyuninstall.ui import workers as _w

    orig_run = _w.Executor.run

    def run_traced(fn, on_result, on_error=None):
        print(f"EXECUTOR submit fn={getattr(fn, '__qualname__', fn)}", flush=True)

        def fn2():
            print(f"  read start thread={threading.current_thread().name}", flush=True)
            try:
                return fn()
            finally:
                print("  read done", flush=True)

        def on2(res):
            print(f"  apply thread={threading.current_thread().name}", flush=True)
            return on_result(res)

        def err2(msg):
            print(f"  WORKER-ERROR: {msg}", flush=True)
            if on_error is not None:
                return on_error(msg)
            return None

        return orig_run(fn2, on2, err2)

    _w.Executor.run = run_traced


def flatpak_scopes() -> list[str]:
    """Installations ('system'/'user') where APP is currently installed."""
    out = sh(["flatpak", "list", "--app", "--columns=application,installation"]).stdout
    scopes = []
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) == 2 and cols[0] == APP:
            scopes.append(cols[1].strip())
    return sorted(scopes)


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


def model_rows_by_id(w: MainWindow) -> dict[str, Any]:
    """instance_id -> Installation for every row currently in the model."""
    return {w._model.at(r).instance_id: w._model.at(r) for r in range(w._model.rowCount())}


def select_instance(w: MainWindow, instance_id: str) -> bool:
    """Select the row whose source row has this instance_id; True if found."""
    w.search.clear()
    model, proxy = w._model, w._proxy
    for src_row in range(model.rowCount()):
        if model.at(src_row).instance_id != instance_id:
            continue
        idx = proxy.mapFromSource(model.index(src_row, 0))
        if not idx.isValid():  # proxy not yet laid out — force it
            proxy.invalidate()
            idx = proxy.mapFromSource(model.index(src_row, 0))
        if not idx.isValid():
            continue
        w.table.selectRow(idx.row())
        w.table.setCurrentIndex(idx)
        return True
    return False


def fail_all(reason: str) -> None:
    check("harness aborted", False, reason)
    finish()


def finish() -> None:
    failures = [r for r in RESULTS if not r[1]]
    payload = {
        "harness": "gui-tests-3 (QA M flatpak)",
        "app": APP,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checks": [{"label": lbl, "pass": ok, "detail": det} for lbl, ok, det in RESULTS],
        "total": len(RESULTS),
        "failed": len(failures),
    }
    (SHOTS / "gui-qa3-results.json").write_text(json.dumps(payload, indent=2))
    print("\n=== FLATPAK (QA M) ACCEPTANCE SUMMARY ===", flush=True)
    print(f"{len(RESULTS)} checks, {len(failures)} failed", flush=True)
    for lbl, _ok, det in failures:
        print(f"  FAIL: {lbl} — {det}", flush=True)
    # Exit directly: returning through app.exec() would give main() a0 exit
    # code and mask failures; all output above is flushed and the JSON is on
    # disk before this call.
    os._exit(len(failures))


def main() -> int:
    QApplication.setApplicationName(APP_ID)
    QApplication.setOrganizationName("CachyOS")
    app = QApplication([])
    app.setStyleSheet(stylesheet(LIGHT))
    _instrument_executor()

    check("M-00 preconditions: flatpak + both scopes", flatpak_scopes() == ["system", "user"], str(flatpak_scopes()))
    if RESULTS[-1][1] is False:
        fail_all("preconditions unmet")
        return app.exec()

    S["history_before"] = len(HistoryStore().entries())
    S["pacman_before"] = len([x for x in sh(["pacman", "-Qq"]).stdout.splitlines() if x.strip()])

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
        settings=load_settings(),
        history=HistoryStore(),
        helper=HelperClient(),
        flatpak=flatpak,
        installations=installations,
    )

    window = MainWindow(state)
    window.resize(1366, 768)
    window.show()
    window.activateWindow()
    window.populate_cleanup_apps()
    _start_enrichment(window)
    S["window"] = window
    S["app"] = app
    print("boot ok", flush=True)

    pump_until(
        lambda: bool(window._state.identities),
        180,
        lambda _r: step_listed(),
        lambda why: fail_all(f"enrichment never finished ({why})"),
        interval_ms=300,
    )
    return app.exec()


# ------------------------------------------------------------------- steps
def step_listed() -> None:
    """Enrichment landed: both flatpak rows must have survived refresh_state."""
    w: MainWindow = S["window"]
    rows = model_rows_by_id(w)
    check("M-01 system row listed after enrichment", SYS_ID in rows, f"ids sample={list(rows)[:6]}")
    check("M-02 user row listed after enrichment (both scopes)", USR_ID in rows, f"total rows={len(rows)}")
    raw_ids = [w._model.at(r).instance_id for r in range(w._model.rowCount())]
    check(
        "M-02b no duplicate rows after enrichment",
        len(raw_ids) == len(set(raw_ids)),
        f"rowCount={len(raw_ids)} unique={len(set(raw_ids))}",
    )
    ok_origin = SYS_ID in rows and rows[SYS_ID].origin is Origin.FLATPAK
    check("M-03 origin is Flatpak", ok_origin, str(rows[SYS_ID].origin) if SYS_ID in rows else "row missing")

    if not (SYS_ID in rows and USR_ID in rows):
        fail_all("flatpak rows missing after enrichment — scope listing broken")
        return

    w.search.setText("Calculator")
    later(350, _shot_listed)


def _shot_listed() -> None:
    w: MainWindow = S["window"]
    grab(w, "14-flatpak-both-scopes.png")
    check(
        "M-04 screenshot both scopes listed",
        (SHOTS / "14-flatpak-both-scopes.png").stat().st_size > 3000,
    )
    w.search.clear()
    later(250, step_system_removal)


# ------------------------------------------------- system-scope removal
def step_system_removal() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "marker.txt").write_text("qa-m data marker (system cycle)\n")
    check("M-05 data marker seeded", (DATA_DIR / "marker.txt").exists(), str(DATA_DIR))

    w: MainWindow = S["window"]
    if not select_instance(w, SYS_ID):
        fail_all("could not select the system-scope row")
        return
    # Schedule the pump BEFORE the click: the confirm box opens a nested
    # loop synchronously inside click() (Ctrl+R lesson from harness #2).
    pump_until(find_dialog(QMessageBox), 15, _on_system_confirm, lambda why: fail_all(f"confirm box missing: {why}"))
    w.uninstall_btn.click()


def _on_system_confirm(box: QMessageBox) -> None:
    text = box.text()
    check("M-06 confirm box names system scope", "system scope" in text, box.text().replace("\n", " | "))
    check("M-07 confirm box discloses --delete-data", "--delete-data" in text, "")
    grab(box, "15-flatpak-confirm-scope.png")
    box.button(QMessageBox.StandardButton.Yes).click()
    pump_until(find_dialog(QMessageBox), 60, _on_system_removed_box, lambda why: fail_all(f"no result box: {why}"))


def _on_system_removed_box(box: QMessageBox) -> None:
    ok = box.windowTitle() == "Removed" and "was removed by Flatpak" in box.text()
    check("M-08 system removal reported success", ok, f"{box.windowTitle()}: {box.text()[:120]}")
    grab(box, "16-flatpak-system-removed.png")
    box.accept()
    pump_until(
        lambda: SYS_ID not in model_rows_by_id(S["window"]) and USR_ID in model_rows_by_id(S["window"]),
        120,
        lambda _r: _verify_system_removed(),
        lambda why: _diag_refresh(why),
    )


def _diag_refresh(why: str) -> None:
    w: MainWindow = S["window"]
    rows = model_rows_by_id(w)
    print(f"DIAG ({why}): rows={len(rows)} flatpak_ids={[i for i in rows if i.startswith('flatpak:')]}", flush=True)
    pool = QThreadPool.globalInstance()
    print(f"DIAG threadpool active={pool.activeThreadCount()} max={pool.maxThreadCount()}", flush=True)
    t0 = time.monotonic()
    fp = FlatpakProvider().list_installations()
    print(f"DIAG inline flatpak list: {time.monotonic() - t0:.2f}s -> {[i.instance_id for i in fp]}", flush=True)
    t0 = time.monotonic()
    sess = AlpmSession()
    sess.open()
    pk = sess.packages(with_origin_resolution=True)
    print(f"DIAG inline alpm full: {time.monotonic() - t0:.2f}s pkgs={len(pk)}", flush=True)
    hist = HistoryStore().entries()
    print(f"DIAG last history: {[(e.action, e.subject, e.provider, e.result) for e in hist[-3:]]}", flush=True)
    fail_all(f"table not refreshed after system removal: {why}")


def _verify_system_removed() -> None:
    w: MainWindow = S["window"]
    rows = model_rows_by_id(w)
    check("M-09 system row gone, user row survives", USR_ID in rows and SYS_ID not in rows, "")
    scopes = flatpak_scopes()
    check("M-10 CLI: only user scope remains", scopes == ["user"], str(scopes))
    check(
        "M-11 --delete-data removed ~/.var/app (system cycle)",
        not DATA_DIR.exists(),
        str(DATA_DIR),
    )
    hist = HistoryStore().entries()
    last = hist[0] if hist else None  # entries() is newest-first (ORDER BY id DESC)
    ok_hist = (
        last is not None
        and last.provider == "flatpak"
        and last.subject == APP
        and last.result == "success"
        and getattr(last, "detail", None) and "system" in str(getattr(last, "detail"))
    )
    check(
        "M-12 history recorded flatpak uninstall with scope",
        ok_hist,
        str({k: getattr(last, k, None) for k in ("action", "subject", "provider", "result", "detail")}) if last else "none",
    )
    grab(w, "17-flatpak-after-system-removal.png")
    later(300, step_user_removal)


# ---------------------------------------------------- user-scope removal
def step_user_removal() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "marker.txt").write_text("qa-m data marker (user cycle)\n")

    w: MainWindow = S["window"]
    if not select_instance(w, USR_ID):
        fail_all("could not select the user-scope row")
        return
    pump_until(find_dialog(QMessageBox), 15, _on_user_confirm, lambda why: fail_all(f"confirm box missing: {why}"))
    w.uninstall_btn.click()


def _on_user_confirm(box: QMessageBox) -> None:
    check("M-13 confirm box names user scope", "user scope" in box.text(), box.text().replace("\n", " | "))
    box.button(QMessageBox.StandardButton.Yes).click()
    pump_until(find_dialog(QMessageBox), 60, _on_user_removed_box, lambda why: fail_all(f"no result box: {why}"))


def _on_user_removed_box(box: QMessageBox) -> None:
    ok = box.windowTitle() == "Removed" and "was removed by Flatpak" in box.text()
    check("M-14 user removal reported success", ok, f"{box.windowTitle()}: {box.text()[:120]}")
    box.accept()
    pump_until(
        lambda: all(not iid.startswith("flatpak:") or APP not in iid for iid in model_rows_by_id(S["window"])),
        90,
        lambda _r: _verify_user_removed(),
        lambda why: fail_all(f"table not refreshed after user removal: {why}"),
    )


def _verify_user_removed() -> None:
    w: MainWindow = S["window"]
    rows = model_rows_by_id(w)
    leftover = [iid for iid in rows if APP in iid]
    check("M-15 no Calculator rows remain in table", not leftover, str(leftover))
    scopes = flatpak_scopes()
    check("M-16 CLI: removed from both scopes", scopes == [], str(scopes))
    check(
        "M-17 --delete-data removed ~/.var/app (user cycle)",
        not DATA_DIR.exists(),
        str(DATA_DIR),
    )
    hist = HistoryStore().entries()
    flatpak_entries = [e for e in hist if e.provider == "flatpak"]
    check(
        "M-18 two flatpak history entries (system + user)",
        len(hist) >= S["history_before"] + 2 and len(flatpak_entries) >= 2,
        f"before={S['history_before']} total={len(hist)} flatpak={len(flatpak_entries)}",
    )
    pacman_now = len([x for x in sh(["pacman", "-Qq"]).stdout.splitlines() if x.strip()])
    check(
        "M-19 pacman DB untouched by flatpak removals",
        pacman_now == S["pacman_before"],
        f"{S['pacman_before']} -> {pacman_now}",
    )
    grab(w, "20-flatpak-all-removed.png")
    finish()


if __name__ == "__main__":
    raise SystemExit(main())

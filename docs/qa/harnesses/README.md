# Archived QA harnesses

Physical/test harnesses used during the certification campaign, archived after
their recorded runs. Their results live in `docs/screenshots/`
(`gui-qa-results.json`, `gui-qa2-results.json`, `gui-qa3-results.json`) and in
`docs/QA_MANUAL.md`.

| Harness | Certified | Result |
|---|---|---|
| `_gui_tests.py` | QA A + K (GUI uninstall flow, progress, quarantine) | 37/37 PASS, shots 01–08 |
| `_gui_tests2.py` | QA C + N-keyboard (orphan tab truth, physical orphan removal, `/`·arrows·Delete·Esc·Ctrl+R) | 27/27 PASS, shots 09–13 |
| `_live_tests.py` | Live D-Bus/CLI acceptance (removal, stale plan, lock, denial) | PASS |
| `_physical_fs_tests.py` | Physical filesystem safety (shared data, symlink, ownership, Exec, quarantine) | 20/20 PASS |
| `_probe_dbus.py`, `_probe_dbus2.py` | D-Bus API probes (signal members, malformed input) | PASS |
| `_debug_remove.py` | One-off removal debugging (A/B for D20) | superseded by evidence in DECISIONS |
| `_pkgcert.sh` | Package-certification cycle (makepkg → pacman -U → -R audit → reinstall) | PASS |
| `_gui_tests3.py` | QA M (Flatpak: both scopes listed after enrichment, scope-named confirm, `--delete-data`, history scope detail, pacman DB untouched, runtimes untouched) | **21/21 PASS**, shots 14–17 + 20 |

Re-run notes: harnesses resolve screenshots via `parents[3]/docs/screenshots`,
i.e. they must run from anywhere with the repo intact; they drive the
**installed** app (`cachyuninstall` on `PYTHONPATH` or system-installed) with
`QT_QPA_PLATFORM=offscreen` inside the disposable container.
`_gui_tests3.py` additionally needs both flatpak scopes installed and must run
under `dbus-run-session --` (D24: flatpak's post-removal session step returns
rc=1 without a session bus). No harness is part of
`scripts/validate-release.sh` (that gate lints only `src` and `tests`).

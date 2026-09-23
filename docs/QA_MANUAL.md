# QA MANUAL — release checklist

Every item maps to the master specification acceptance tests (§276–289).
Perform in a disposable environment (VM or container with a CachyOS/Arch
image) when an item is destructive.

Evidence notation: `docs/qa/harnesses/_gui_tests.py` = GUI harness (offscreen, real system),
`docs/qa/harnesses/_gui_tests2.py` = orphan/keyboard harness,
`docs/qa/harnesses/_gui_tests3.py` = Flatpak (QA M) harness, `docs/qa/harnesses/_physical_fs_tests.py` = physical
filesystem safety suite, `docs/qa/harnesses/_live_tests.py` = live D-Bus/CLI suite,
`PA-xx` = physical acceptance runs recorded in `RELEASE_READINESS.md`.
Screenshots live in `docs/screenshots/` (results JSON alongside them).

## A. Pacman flow (§276)

- [x] Launch, search an installed app, open details: metadata matches
      `pacman -Qi` (name/version/size/deps/required-by).
      — GUI-06 (version26.08.1-1 vs pacman), GUI-04/05, screenshots 01/02.
- [x] Plan uninstall → preview shows REMOVE / orphans / KEEP / USER DATA /
      PROTECTED sections with reasons per item.
      — GUI-10/12/13, ORP-05/06, screenshot 06.
- [x] Cancel closes without side effects.
      — GUI-16/17/18, ORP-08..11 (Esc + button cancel).
- [x] Confirm → polkit dialog → real progress events (no fake percentages).
      — GUI-20b/ORP-14 (real stage text, bar reaches 100; events are
      libalpm's own). Polkit: root auto-approves in the container (no
      agent); the deny path is certified under J.
- [x] After success: app gone from list (`pacman -Q` agrees), history entry
      exists, selected leftovers removed or quarantined, report shows counts.
      — GUI-21..29, ORP-15/16/20/21, screenshots 08/13.

## B. Shared dependency (§277)

- [x] Two apps sharing a lib: uninstall A → lib kept and listed under KEEP;
      app B still runs/package present.
      — konsole/gedit removed; KEEP section shown in preview (screenshot 06);
      cairo/glib2/pango/qt6-base still installed; qt6-base still Required By
      44 installed packages; B = `appstream` runs (`AppStream 1.2.0`),
      `attica` present; PA-03: removing a shared lib itself is blocked with
      requirers named.

## C. Orphan (§278)

- [x] Remove an app with private deps (opt-in) → deps appear in Orphans tab →
      remove an orphan from Orphans with preview.
      — konsole E2E created the KDE orphans; tab matches full-detail + CLI
      (ORP-01..03, 8/8); gspell removed from the tab with preview
      (ORP-05..16); `enchant` appeared after (ORP-17/18); cascade opt-in
      stays OFF (ORP-07). Fixed bugs: light-mode over-report (508 vs 8,
      D19) and post-removal staleness (`refresh_state`, D19).

## D. Leftovers (§279)

- [x] Seed `~/.config|cache|.local/share/<app>` for a fake package, scan →
      HIGH/MEDIUM candidates with correct categories and reasons.
      — `docs/qa/harnesses/_physical_fs_tests.py` (gedit seeds) + live konsole scan
      (config HIGH "named exactly after the application", data HIGH).

## E. Shared user data (§280)

- [x] Directory whose token matches another installed app → PROTECTED, cannot
      be checked, reason names the other application.
      — `docs/qa/harnesses/_physical_fs_tests.py` shared-user-data case PASS.

## F. Symlink (§281)

- [x] `~/.config/x -> ~/important`: cleaning x removes the link only; target
      untouched.
      — `docs/qa/harnesses/_physical_fs_tests.py` symlink case PASS.

## G. Ownership (§282)

- [x] Path owned by another package → PROTECTED with the owning package named.
      — `docs/qa/harnesses/_physical_fs_tests.py` ownership case PASS.

## H. Stale plan (§283)

- [x] Preview, then `pacman -S something` in a terminal, then confirm →
      helper refuses with "system changed".
      — PA-06 (`StalePlan`, generation + digest).

## I. Lock (§284)

- [x] Hold the pacman lock (long pacman -S elsewhere) → "Another package
      operation is running"; lockfile untouched.
      — PA-08 (`PackageManagerBusy`, `db.lck` never deleted).

## J. Authorization denied (§285)

- [x] Cancel the polkit prompt → "Authorization denied", zero changes
      (verify `pacman -Q` and filesystem).
      — polkit denial as user `tester`: `authorization-denied`, vim and the
      filesystem untouched.

## K. Malformed helper input (§286)

- [x] `busctl call org.cachyos.Uninstall /org/cachyos/Uninstall
      org.cachyos.Uninstall Call s 'garbage'` → protocol-error reply.
      — malformed D-Bus suite 8/8; helper alive and journal clean after.

## L. .desktop Exec (§287)

- [x] Malicious Exec in a user desktop file → parsed as data, never executed.
      — `tests/security` + physical FS suite Exec case PASS.

## M. Flatpak (§289) — when flatpak installed

- [x] Listed with Flatpak origin; uninstall removes app + `--delete-data`;
      scope respected (`--user` vs system).
      — `docs/qa/harnesses/_gui_tests3.py` **21/21 PASS** in the container
      under `dbus-run-session` (D24) with `org.gnome.Calculator` in **both**
      scopes: both rows survive enrichment with `Origin.FLATPAK`,
      duplicate-free table (M-01..04, shot 14); confirm dialog names the
      scope and `--delete-data` (M-06/07, shot 15); physical system
      uninstall while both scopes exist — the exact ambiguity-probe case —
      removes only the system app + its data, user scope untouched, history
      entry with `scope=system` (M-08..12, shot 17); user cycle removes the
      last row and its data (M-13..17, shot 20); 2 Flatpak history
      entries; pacman DB 541→541; `org.gnome.Platform` runtimes still
      installed afterwards (D17 boundary, row 18). Three defects found and
      fixed by this run (D24): unscoped argv hangs on flatpak's
      interactive disambiguation prompt, `refresh_state` dropped
      non-ALPM rows, `replace_rows` froze/duplicated the boot rows.

## N. General

- [ ] Startup under Plasma/Wayland and an X11 session; 1366x768 usable.
      — **NOT CERTIFIED**: the disposable container has no compositor or
      display server; Qt offscreen at 1366x768 is certified instead
      (GUI-02). Requires a real desktop session.
- [x] Keyboard-only operation: `/` search, arrows, Delete, Esc, Ctrl+R —
      GUI-04, KBD-01..04, GUI-10, ORP-08.
      **Ctrl+, is NOT CERTIFIED**: no preferences/binding exists in this
      release (only `/`, Ctrl+R, Delete are bound).
- [x] `cachyuninstall --list/--orphans/--dry-run/--leftovers --json` parse
      cleanly with `jq`.
- [x] No network traffic during any core flow (watch with a proxy or tcpdump).
      — `strace -f -e trace=network` over all four core commands: a single
      bare `socket(AF_INET6, SOCK_DGRAM)` creation, **zero** connect/send.
- [x] Uninstall CachyUninstall itself via pacman leaves no stray files beyond
      documented user dirs. — `makepkg -f` → `pacman -U` → `pacman -R`: all
      166 tracked entries removed (only shared hierarchy dirs remain, e.g.
      `/usr/share/applications/`), runtime `__pycache__` cleaned (Arch pycache
      hook), **no helper process** surviving `-R` (fixed in
      `cachyuninstall.install`), no `/var/tmp/systemd-private-*` stray,
      `find /usr /etc /var -name '*cachyuninstall*' -o -name '*org.cachyos*'`
      → nothing; `~/.local/share/cachyuninstall` (history) remains as the
      documented user dir. Reinstall afterwards verified working.

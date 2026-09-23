# PROGRESS

Format per phase: Completed / Evidence / Limitations / Next.
"Completed" means code + tests, not just code. Verified on the live CachyOS
dev host (see docs/RECON/RECON.md) unless marked otherwise.

## Phase 0 — Recon
- **Completed**: host/API probing (CachyOS rolling, Python 3.14.7, pacman
  7.1.0/libalpm 16.0.1, pyalpm 0.12.0, polkit 127, dbus 1.16.2, Qt 6.11.2;
  flatpak absent; shelly is the local helper). pyalpm/pytest-qt/QtDBus APIs
  verified by live probes (Handle/Transaction surface, `db.get_pkg`,
  init_transaction kwargs, trailing-QDBusMessage caller injection,
  QDBus.CallMode enum location, QDBusArgument's lack of struct extraction).
- **Docs**: `docs/RECON/RECON.md`, `docs/REQUIREMENTS.md`, `docs/DECISIONS.md` (D1-D24).

## Phase 1 — Foundation
- **Completed**: project config (pyproject, ruff, mypy strict, pre-commit, CI),
  package skeleton, domain model, error taxonomy.
- **Gates**: `ruff check` clean, `mypy --strict` clean (37 modules).

## Phase 2 — ALPM
- **Completed**: `AlpmSession` (thread-affine, lazy-open, syncdb probing with
  pacman-precedence origin map (D16), generation marker, owner index,
  two-tier `packages()` (§145 measure-driven: light=113 ms, full=898 ms for
  1411 packages on the dev host)).
- **Tests**: mapping/origin/orphan/ownership/generation units + read-only
  integration against the real DB (enumerates >1400 pkgs, glibc removal
  blocked with full reverse-dep list, `/usr/bin/pacman` owned by pacman).

## Phase 3 — Application model
- **Completed**: desktop-entry parser (untrusted-input safe: never executes
  `Exec`; localized keys; field-code stripping), identity graph
  (package ↔ desktop ids ↔ executables ↔ icons), dedup tokens.

## Phase 4 — List UI
- **Completed**: main window (Applications/Orphans/Cleanup/History tabs),
  sortable/filterable table, details panel (deps, reverse deps, files, backup
  files, raw metadata), dark/light Breeze-inspired themes, keyboard shortcuts,
  offscreen UI tests (model/filter/preview defaults).

## Phase 5 — Removal planner
- **Completed**: `RemovalPlanner` over pure domains: blocked-with-blockers,
  shared-dep KEEP listing, becoming-orphan simulation (fixpoint), opt-in
  cascade, plan digest. Tests over worlds A-E/H from the spec fixtures.

## Phase 6 — Privilege service
- **Completed**: D-Bus system service (`org.cachyos.Uninstall`, QtDBus),
  polkit `CheckAuthorization` (dbus-python — PyQt6 cannot demarshal the
  reply struct; measured and documented), strict JSON protocol v1
  (unknown ops/fields rejected, name grammar, size caps), generation +
  digest staleness gate (D3), transaction backend with verified pyalpm
  callbacks (default-deny questioncb), best-effort interrupt (D5).
- **Tests**: HelperCore fully unit-tested over FakeBackend (auth denial,
  staleness, digest tampering, vanished package, fuzz-shaped payloads, cancel,
  no-traceback leakage).

## Phase 7 — Execution/progress
- **Completed**: worker-thread transactions in helper, live Progress signals,
  nested-event-loop cancel handling in service adaptor, journal start/finish,
  post-removal history entry, success/partial/failed result reporting.

## Phase 8 — Leftover engine
- **Completed**: rule registry (CONFIG/CACHE/DATA/STATE/AUTOSTART/USER-DESKTOP/
  SYSTEMD-USER), exact-token matching, ownership veto via package-file index,
  cross-identity sharing protection, size measurement (allocated bytes),
  LOW hidden by default. Property test proves: an owned path is NEVER a
  selectable candidate.

## Phase 9 — Cleanup UX
- **Implemented**: Cleanup tab (scan any installed app, reasons per item,
  select/clean), quarantine with manifest + restore, policy-gated fd-based
  deletion with dev+ino re-verification at execution.

## Phase 10 — Orphans
- **Implemented**: Orphans tab (static orphans from local DB) + removal flow
  reuse of the preview/privilege pipeline.

## Phase 11 — Flatpak
- **Completed**: availability detection, listing (argv, no shell),
  `flatpak uninstall --delete-data` with scope handling (D17). The dev host
  has no flatpak, so behavior there is provider-unavailable (verified).
  Physical certification: **CERTIFIED — see Phase 18**.

## Phase 12 — AppImage / manual
- **Implemented (D8 boundary)**: discovery from configured dirs; inspection
  only, no removal verb in v1.

## Phase 13 — History / settings / journal
- **Implemented**: SQLite history + crash journal, settings JSON with typed
  load/save, quarantine manifests. Dependency-explainer: dependency tree is
  an expandable section of the details panel (dependencies/reverse deps).

## Phase 14 — Evidence-backed application data rules (NEW)
- **Implemented**: `AppDataRule` registry for known application data locations
  that don't follow simple token matching. First regression case: Firefox
  profiles in `~/.mozilla/firefox/<profile>/` with verification via
  profile markers (prefs.js, cert9.db, key4.db, places.sqlite, profiles.ini).
- **Tests**: 13 new tests covering detection, verification, ownership
  protection, sharing protection, and confidence levels.
- **Confidence model**: MEDIUM for known location, HIGH when verification
  passes (profile markers or profiles.ini).

## Phase 15 — Physical destructive acceptance (CERTIFIED)
- **Environment**: disposable `systemd-nspawn` container
  (`cachyuninstall-test`, Arch base + CachyOS repos, systemd/D-Bus/polkit,
  GUI offscreen). No Docker/Podman/KVM available.
- **Completed (physical, real system changes)**: package removal
  (gedit → 0/1389 files remain), shared-dependency block (PA-03),
  orphan cascade opt-in (konsole:30 packages, shared deps survived),
  stale-plan rejection (PA-06 `StalePlan`), DB-lock (PA-08
  `PackageManagerBusy`, `db.lck` untouched), polkit denial (tester user →
  `authorization-denied`, zero changes), malformed D-Bus suite 8/8,
  physical filesystem-safety suite 20/20 (shared user data, symlink,
  ownership, `.desktop` Exec, quarantine, path policy), leftover scans
  (gedit seeds + live konsole), history roundtrip.
- **GUI harness #1**:37/37 (`_gui_tests.py`) incl. real progress events,
  screenshots 01–08.
- **GUI harness #2**:27/27 (`_gui_tests2.py`) — orphan tab = full-detail =
  CLI (8/8), physical orphan removal, post-removal refresh (D19),
  keyboard `/`·arrows·Delete·Esc·Ctrl+R, screenshots 09–13.
- **Critical bugs found + fixed + physically A/B verified**:
  helper unit `ProtectSystem=strict` made the helper *report success while
  keeping every file* (D20); D-Bus progress signal member is `progressed`
  (D21, `busctl introspect`); light-mode orphan over-report508 vs8 (D19).
- **Evidence**: `docs/screenshots/` (PNGs + `gui-qa-results.json`,
  `gui-qa2-results.json`), `docs/QA_MANUAL.md` checkmarks.

## Phase 16 — Packaging certification (CERTIFIED)
- **Completed**: PKGBUILD ↔ `.SRCINFO` byte-identical (`makepkg --printsrcinfo`
  diff), namcap clean of E-level after D23 fixes (hicolor dep, dbus conf →
  `/usr/share/dbus-1/system.d`), `makepkg` `check()` runs107 tests,
  documented `build-aur/` staging flow proven (repo `src/` stays clean),
  `pacman -U` → helper active + D-Bus policy enforced (garbage call →
  `protocol-error`), **self-uninstall**: `pacman -R` removes all166 tracked
  entries, runtime `__pycache__` cleaned, no surviving daemon (fixed in
  `cachyuninstall.install`), no stray files anywhere; only
  `~/.local/share/cachyuninstall` (documented user data) remains. Reinstall
  verified. Release gate `scripts/validate-release.sh` passes end-to-end.

## Phase 17 — Documentation & audits (CERTIFIED)
- **Completed**: AI-slop scan (zero phrase hits; one `🛡` emoji removed from
  UI), leftover-rule audit (7 generic token rules +1 evidence-backed
  Firefox rule; zero app-specific rules; no pre-release DB expansion),
  docs audit (README/CHANGELOG/PACKAGING/SECURITY updated — SECURITY.md no
  longer documents the removed `ProtectSystem=strict`), screenshots in
  AppStream metainfo validated (`appstreamcli` OK), `DECISIONS.md` D19–D24.

## Phase 18 — Flatpak physical certification (CERTIFIED)
- **Environment**: flathub remote; `org.gnome.Calculator` +
  `org.gnome.Platform//51` installed in **both** system and user scopes in
  the container; GUI harness run under `dbus-run-session` (D24: flatpak's
  own post-removal session step returns rc=1 with no session bus — every
  real desktop has one).
- **Physical probes found three real defects (fixed, D24)**:
  1. unscoped `flatpak uninstall` **hangs** on flatpak's interactive
     disambiguation prompt when the app exists in both scopes (would stall
     the GUI's 30 s captured subprocess) → argv now always pins
     `--system`/`--user`, unit tests pin the exact vector;
  2. `refresh_state` dropped Flatpak/Manual rows and `_uninstall_flatpak`
     never refreshed after success → read() merges all three providers,
     success path refreshes;
  3. `replace_rows` re-appended the *boot-time* non-pacman rows → a removed
     Flatpak row resurrected forever and rows doubled each refresh →
     wholesale replace (single caller supplies the full merged set).
- **GUI harness #3**: **21/21 PASS** (`docs/qa/harnesses/_gui_tests3.py`):
  both scopes listed after enrichment (`Origin.FLATPAK`, dup-free543-row
  table), scope-named confirm dialogs disclosing `--delete-data`, physical
  system uninstall while both scopes exist (the ambiguity case) removing
  only the system app + its data, user scope untouched, history entries
  with scope detail, user cycle, pacman DB 541→541, `org.gnome.Platform`
  runtimes untouched afterwards (D17 boundary). Screenshots 14–17 + 20,
  `gui-qa3-results.json`, probe transcript `docs/qa/flatpak-scope-probe.txt`.

## Measured performance (dev host, 1411 packages, SSD ext4)

| Metric | Value | Target |
|---|---|---|
| Phase-1 table-ready data | ~113 ms | <600 ms cold (§83) ✓ |
| Phase-2 origin+identity enrichment (background) | ~0.9 s | (background, no target) |
| Planner analyze() for firefox | ~14 ms | <300 ms (§141) ✓ |
| Full tests | 122 (98 unit +8 security +1 property +10 ui +5 integration) ~17 s | <60 s ✓ |

Container (physical flows): CLI `--list`0.61 s, `--orphans`0.60 s,
`--dry-run`0.46 s, `--leftovers`2.04 s, full GUI removal ~1.2 s.

## Phases 15-18 — remaining before any release tag

- [x] Physical install/uninstall acceptance in a disposable environment (QA_MANUAL A–L, N-core).
- [x] Screenshot pass + real screenshots into metainfo (never generated data).
- [x] Packaging certification (PKGBUILD/.SRCINFO/namcap/makepkg/self-uninstall).
- [x] Flatpak removal physical certification (Phase 18 — harness #3 21/21).
- [ ] Real desktop session smoke test (Plasma/Wayland + X11,1366×768) — needs a
      graphical session outside the container; NOT CERTIFIED in this campaign.
- [ ] AUR/CachyOS repo publication (not claimed until actually done).

## Known limitations (tracked, honest)

* Owner-index build is ~6.6 s on the dev host → lazy (D-spec §145), runs
  inside analysis workers only; startup never pays it.
* Leftover discovery is conservative by design (see docs/LEFTOVER_DETECTION.md
  limitations). Non-identity-named app data is intentionally invisible.
* Mid-commit cancellation is best-effort; label copy states this (D5).
* Firefox data in `~/.mozilla/firefox` only detected when Firefox is installed
  via pacman (identity must exist in local DB).
* `Ctrl+,` has no binding (no preferences UI in this release) — QA N keyboard
  sub-item NOT CERTIFIED; bound shortcuts (`/`, arrows, Delete, Esc, Ctrl+R)
  are physically certified.
* Two same-ID flatpak rows (system + user) are visually identical in the
  table; the scope is disclosed in the confirmation dialog before any action.
* Flatpak post-removal needs a session D-Bus (flatpak's own step; present on
  any real desktop) — headless runs use `dbus-run-session` (D24).

## Automated tests: PASS (98 unit +8 security +1 property +10 ui +5 integration =122)
## Release gate: PASS on the final tree (ruff + format + mypy --strict + tests + desktop/appstream/polkit validation; wheel build skipped when python-build is absent)
## Live read-only integration: PASS (enumeration, ownership, planner, identity)
## Physical destructive acceptance: PHYSICALLY CERTIFIED (container, harnesses1/2 + suites + PA-01..08)
## Packaging certification: PHYSICALLY CERTIFIED (makepkg/namcap/pacman -U/-R cycle)
## Real Flatpak certification: PHYSICALLY CERTIFIED (Phase18, harness #321/21, D24)
## Evidence-backed leftover rules: IMPLEMENTED + audit PASSED (no pre-release expansion)

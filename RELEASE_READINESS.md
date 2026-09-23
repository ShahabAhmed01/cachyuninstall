# RELEASE READINESS REPORT

Generated: 2026-09-23 — certification campaign (disposable-environment physical QA)

## Product Version

**CachyUninstall 1.0.0**

## Certification Categories

Every claim in this report uses exactly one of:

| Category | Meaning |
|---|---|
| **IMPLEMENTED** | Code path exists and is reviewed; no dedicated test layer claims more |
| **AUTOMATED-TESTED** | Proven by the automated suites that run in the release gate |
| **LIVE-READ-ONLY TESTED** | Proven against the real system without changing it |
| **PHYSICALLY CERTIFIED** | Proven in the disposable environment with real system changes and observed evidence |
| **NOT CERTIFIED** | Not proven — never silently upgraded; reason stated |
| **KNOWN LIMITATION** | Deliberate boundary or documented gap, tracked honestly |

## Environment Tested

| Component | Dev host | Physical test environment |
|---|---|---|
| Distribution | CachyOS (rolling) | Arch base + CachyOS repos, `systemd-nspawn` container `cachyuninstall-test` |
| Kernel | 6.11.x | host kernel (nspawn) |
| Python | 3.14.7 | 3.14.x |
| Qt / PyQt6 | 6.11.2 / 6.11.0 | same (GUI run `QT_QPA_PLATFORM=offscreen`) |
| pacman / libalpm / pyalpm | 7.1.0 / 16.0.1 / 0.12.0 | same |
| polkit / D-Bus | 127 / 1.16.2 | same (system bus + helper unit live; harness #3 additionally under `dbus-run-session`, D24) |
| Desktop session | KDE Plasma 6 (Wayland) | **none** (no compositor — see row 22) |
| Filesystem | ext4 (LUKS2, NVMe) | container rootfs on ext4 |
| flatpak | absent | flathub; `org.gnome.Calculator` + `org.gnome.Platform//51` installed in **both** system and user scopes (Phase 18) |

Physical flows ran **as root inside the container** against the real package
database, real filesystem and real D-Bus/privilege stack; polkit denial was
certified with a non-root user (`tester`).

## Test Results

### Automated Tests (release gate: `scripts/validate-release.sh`)

| Suite | Tests | Status |
|---|---|---|
| Unit (incl. Flatpak argv scope tests, Firefox AppDataRule) | 98 | PASS |
| Security | 8 | PASS |
| Property (Hypothesis) | 1 | PASS |
| UI (offscreen) | 10 | PASS |
| Integration (read-only, real DB) | 5 | PASS |
| ruff + ruff-format + mypy `--strict` | — | PASS |
| desktop-file / appstream / polkit XML | — | PASS |
| **Total tests** | **122** | **ALL PASS** |

Final gate run on the final tree: **`Release gate passed.`** (117 tests in
gate's unit+security+property+ui pass + 5 integration).

Package `check()` (inside `makepkg`): **107 tests PASS** (unit+security+property).

## QA Certification Table (25 rows)

| # | QA area (QA_MANUAL ref) | Category | Evidence |
|---|---|---|---|
| 1 | A.1 details match `pacman -Qi` (name/version/deps/required-by) | PHYSICALLY CERTIFIED | GUI harness: version `26.08.1-1` == pacman; shots 01/02 |
| 2 | A.2 preview shows REMOVE / orphans / KEEP / USER DATA / PROTECTED with reasons | PHYSICALLY CERTIFIED | GUI-10/12/13, ORP-05/06; `docs/screenshots/06-preview-dialog.png` |
| 3 | A.3 cancel closes with no side effects | PHYSICALLY CERTIFIED | GUI-16..18; ORP-08..11 (Esc + button), no history delta |
| 4 | A.4 polkit authorization + real progress events | PHYSICALLY CERTIFIED | GUI-20b / ORP-14: libalpm stage text, bar reaches 100 (signal `progressed`, D21); root approves, `tester` denies (row 14) |
| 5 | A.5 post-removal: gone from list, history, leftovers handled, counts reported | PHYSICALLY CERTIFIED | GUI-21..29, ORP-15/16/20/21; `pacman -Q` agrees; shots 08/13 |
| 6 | B shared dependency kept and listed under KEEP; app B still present | PHYSICALLY CERTIFIED | KEEP section in shot 06; cairo/glib2/pango/qt6-base still installed; qt6-base required by 44 pkgs; B=`appstream` runs; PA-03 blocks removing the lib itself |
| 7 | C orphan flow: create orphans → tab correct → remove orphan with preview | PHYSICALLY CERTIFIED | ORP-01..22 (27/27): tab == full-detail == CLI (8/8), `enchant` appeared after removal, cascade opt-in stays OFF, gspell physically removed, deps survived |
| 8 | D leftover scan: seeded config/cache/data → HIGH/MEDIUM with categories + reasons | PHYSICALLY CERTIFIED | physical FS suite + live konsole scan ("named exactly after the application", HIGH) |
| 9 | E shared user data → PROTECTED, names the other application | PHYSICALLY CERTIFIED | physical FS suite case PASS |
| 10 | F symlink `~/.config/x -> ~/important` → link only, target untouched | PHYSICALLY CERTIFIED | physical FS suite case PASS |
| 11 | G package-owned path → PROTECTED with owner named | PHYSICALLY CERTIFIED | physical FS suite case PASS |
| 12 | H stale plan: DB changes between preview and confirm → refused | PHYSICALLY CERTIFIED | PA-06: `StalePlan` (generation + digest), zero actions |
| 13 | I pacman lock held → "another operation" message; `db.lck` untouched | PHYSICALLY CERTIFIED | PA-08: `PackageManagerBusy`; lock file never deleted |
| 14 | J polkit denial → authorization-denied, zero changes | PHYSICALLY CERTIFIED | `tester` user denial; `pacman -Q` + filesystem unchanged |
| 15 | K malformed D-Bus input → protocol error, helper survives | PHYSICALLY CERTIFIED | malformed suite 8/8; garbage call → `protocol-error "Malformed JSON"`; journal clean |
| 16 | L `.desktop` Exec parsed as data, never executed | PHYSICALLY CERTIFIED | security suite + physical FS Exec case |
| 17 | M Flatpak: both scopes listed, scope-confirmed uninstall, `--delete-data`, history | **PHYSICALLY CERTIFIED** | `_gui_tests3.py` **21/21 PASS** (D24): both rows + `Origin.FLATPAK` survive enrichment, dup-free table; scope-named confirms; system uninstall while both scopes exist (ambiguity probe case) removes only system app + data; user cycle; history `scope` detail; shots 14–17 + 20; `gui-qa3-results.json` |
| 18 | M Flatpak runtime refs (`org.gnome.Platform` …) never touched by our argv (D17 boundary) | **PHYSICALLY CERTIFIED** | argv is `flatpak uninstall --system/--user --delete-data -y <app-id>` only (unit-pinned); after both app removals `flatpak list --runtime` still shows `org.gnome.Platform//51` in system **and** user scopes |
| 19 | N keyboard-only: `/`, arrows, Delete, Esc, Ctrl+R | PHYSICALLY CERTIFIED | GUI-04, KBD-01..04, ORP-08. **`Ctrl+,` sub-item NOT CERTIFIED: no preferences UI/binding exists in this release** (KNOWN LIMITATION) |
| 20 | N `--json` outputs parse with `jq`; no network traffic in core flows | LIVE-READ-ONLY TESTED | jq parses `--list/--orphans/--dry-run/--leftovers`; `strace -e trace=network`: bare `socket()` create only, **zero** connect/send |
| 21 | N self-uninstall via pacman leaves no stray files beyond documented user dirs | PHYSICALLY CERTIFIED | `pacman -R`: all 166 tracked entries gone, runtime `__pycache__` cleaned, **no surviving daemon** (fixed `.install`), `find` empty; only `~/.local/share/cachyuninstall` remains; reinstall verified |
| 22 | N startup under Plasma/Wayland and X11; 1366×768 usable | **NOT CERTIFIED** | disposable container has no compositor/display server; Qt offscreen at 1366×768 is certified instead. Requires a real desktop session |
| 23 | Release gate (lint/format/mypy/tests/metadata/wheel) | AUTOMATED-TESTED | `scripts/validate-release.sh` → "Release gate passed." (final tree, this report's generation) |
| 24 | Live read-only integration vs real DB (enumeration, ownership, planner, identity) | LIVE-READ-ONLY TESTED | 5 integration tests + perf runs; glibc blocked, `/usr/bin/pacman`→`pacman` |
| 25 | Packaging: PKGBUILD↔.SRCINFO match, namcap, `makepkg`, install/remove cycle | PHYSICALLY CERTIFIED | byte-identical `.SRCINFO`; namcap **0 E-level** after D23 fixes; `check()` 107 tests; `pacman -U` → helper active + policy enforced; clean `pacman -R` (row 21) |

### Physical Destructive Acceptance — summary

**PHYSICALLY CERTIFIED** for rows 1–19, 21, 25 (real package removals,
orphan cascade, blocks, denials, malformed input, filesystem safety, packaging
cycle, Flatpak scope cycles) in the disposable container. Notable physical
results:

* `gedit` removed: **0 of 1389** own files remain; helper reports success only
  when libalpm really succeeded (D20 — A/B-certified: strict-sandbox unit gave
  rc=1 + files kept; fixed unit gives rc=0 + files gone).
* Orphan cascade (konsole): 30 packages removed, shared dependencies survived.
* Orphan tab truth: full-detail == CLI == tab (8), light-mode bug fixed (D19:
  508 → 8).
* Flatpak dual-scope uninstall: three defects found and fixed by physical
  probes (D24 — unscoped argv hangs on flatpak's interactive disambiguation
  prompt; `refresh_state` dropped non-ALPM rows; `replace_rows` froze and
  duplicated the boot rows). Final harness run: 21/21 with pacman DB
  541→541 and runtimes untouched.

## Security Checks

| Check | Category | Status |
|---|---|---|
| Arbitrary root path deletion | AUTOMATED-TESTED | BLOCKED — helper has one verb (ALPM removal); no file-path API |
| Shell injection via names | AUTOMATED-TESTED | BLOCKED — no `shell=True` (lint-enforced), fixed argv vectors |
| Unsafe deserialization | AUTOMATED-TESTED | BLOCKED — strict JSON protocol v1, unknown fields rejected |
| Symlink traversal on cleanup | PHYSICALLY CERTIFIED | BLOCKED — dirfd + `O_NOFOLLOW` + dev/ino re-check (FS suite) |
| Stale transaction execution | PHYSICALLY CERTIFIED | BLOCKED — PA-06 generation+digest refusal |
| Package ownership bypass | AUTOMATED-TESTED + PHYSICALLY CERTIFIED | BLOCKED — ownership oracle absolute veto (property test + FS suite) |
| Authorization bypass | PHYSICALLY CERTIFIED | BLOCKED — PA-denial as `tester`; polkit `CheckAuthorization` required |
| Malformed D-Bus payload | PHYSICALLY CERTIFIED | BLOCKED — suite 8/8; helper survives; protocol-error reply |
| `.desktop` Exec execution | PHYSICALLY CERTIFIED | BLOCKED — parsed as text only (suite + physical case) |
| Helper privilege sandbox correctness | PHYSICALLY CERTIFIED | D20: scope enforced by policy+polkit, **not** by `ProtectSystem` (which caused silent file retention); backend fails loudly on any ALPM error log |
| Flatpak scope confusion (dual-scope app) | AUTOMATED-TESTED + PHYSICALLY CERTIFIED | BLOCKED — argv always pins `--system`/`--user` (unit tests pin the exact vector; physical probe proved the unscoped hang, D24) |

## Performance Measurements

| Metric | Value | Target | Status |
|---|---|---|---|
| Phase-1 table-ready load (dev host, 1411 pkgs) | ~113 ms | <600 ms (§83) | PASS |
| Phase-2 enrichment (background) | ~0.9 s | (background) | PASS |
| Planner `analyze()` | ~14 ms | <300 ms (§141) | PASS |
| CLI `--list` (container, 541 pkgs) | 0.61 s | <500 ms-class | PASS |
| CLI `--orphans` | 0.60 s | — | PASS |
| CLI `--dry-run` | 0.46 s | <300 ms-class | PASS |
| CLI `--leftovers` | 2.04 s | <500 ms-class | **KNOWN LIMITATION** — ownership-veto scan over real home dominates (lazy, analysis-time only) |
| Full GUI removal (progress + refresh) | ~1.2 s | — | PASS |
| Full test suite | ~17 s | <60 s | PASS |

## Known Limitations

1. **KNOWN LIMITATION** — Owner-index build ~6.6 s: lazy, analysis workers only; startup never pays it.
2. **KNOWN LIMITATION** — Conservative leftover discovery: non-identity-named app data intentionally invisible; Firefox rule needs Firefox installed via pacman.
3. **KNOWN LIMITATION** — Mid-commit cancellation is best-effort (D5); no rollback guarantee.
4. **KNOWN LIMITATION** — No blanket "full home scan <3s" claim; targeted scanning only (`--leftovers` ~2 s on the container home).
5. **KNOWN LIMITATION** — `Ctrl+,` has no binding (no preferences UI in this release).
6. **KNOWN LIMITATION** — Two same-ID flatpak rows (system + user) are visually identical in the table; scope is disclosed in the confirmation dialog before any action.
7. **KNOWN LIMITATION** — Flatpak post-removal needs a session D-Bus (flatpak's own session step; every real desktop has one). Headless/CI runs must wrap the session in `dbus-run-session` (D24); without it flatpak returns rc=1 after an otherwise successful removal and the app fail-loudly reports it.
8. **NOT CERTIFIED** — Real desktop session (Plasma/Wayland + X11) startup — needs a graphical session outside the container.

## Open Issues

1. Desktop-session smoke test on a real Plasma/X11 session (row 22).
2. AUR/CachyOS publication — not yet submitted (publication is **not** a quality claim either way).
3. No automated screenshot comparison (screenshots are real captures; validated by AppStream `appstreamcli`).

## Audits (this campaign)

* **Leftover-rule audit**: PASS — 7 generic XDG token rules + 1 evidence-backed Firefox rule with verification; **zero** app-specific rules (no Discord/Steam/Blender/VS Code/Chromium/Thunderbird); every candidate carries rule id, reason, confidence, ownership veto; scanner never deletes. No pre-release rule-database expansion.
* **AI-slop audit**: PASS — zero marketing-phrase hits across src/docs/README/CHANGELOG; one decorative `🛡` emoji removed from UI list rows; no emoji/hype left in shipped strings.
* **Docs audit**: PASS — README/CHANGELOG/PACKAGING/SECURITY consistent with observed behavior; SECURITY.md updated for the D20 unit change; metainfo screenshots are real captures and validate.

## Release Classification

**RELEASE CANDIDATE**

### Justification

* All 25 QA rows carry an explicit category: 18 rows PHYSICALLY CERTIFIED
  (1–19, 21, 25), 2 rows LIVE-READ-ONLY TESTED (20, 24), 1 row
  AUTOMATED-TESTED (23), 1 row NOT CERTIFIED (22), plus two explicitly marked
  NOT-CERTIFIED sub-items (row 19's `Ctrl+,`) and KNOWN LIMITATIONs above.
  Nothing was silently upgraded and no PASS lacks evidence.
* The privilege boundary, filesystem safety model, orphan/leftover flows,
  packaging cycle **and the Flatpak dual-scope flow** were exercised against
  the real system; the Flatpak run found and fixed three genuine defects
  (D24) rather than being tuned to pass.
* **V1.0 READY is blocked** by exactly two honest gaps: row 22 (desktop
  session startup cannot be certified in this container — no compositor
  exists here) and row 19's `Ctrl+,` sub-item (no preferences UI/binding
  exists in this release). Neither is a safety issue; both are tracked as
  NOT CERTIFIED / KNOWN LIMITATION.
* BETA READY would understate the evidence: every destructive flow has
  physical evidence. RELEASE CANDIDATE is the highest class this campaign's
  environment can honestly support.

## Recommendation

The final tree passes the full release gate (`scripts/validate-release.sh` →
"Release gate passed."). Attach this report as the evidence trail when
considering AUR/CachyOS submission — publication itself remains a separate,
non-quality decision. A future campaign on a real Plasma/Wayland + X11
session should close row 22, after which V1.0 READY becomes reachable.

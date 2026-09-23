# DECISIONS

Every entry follows: Problem / Original assumption / Evidence / Options / Decision / Why / Security impact / UX impact.

---

## D1 — pyalpm is the mandatory transaction engine; no PackageKit

- **Problem**: Which engine executes Arch package removal?
- **Original assumption (prompt §81)**: libalpm/pyalpm by default; PackageKit rejected unless evidence favors it.
- **Evidence**: pyalpm 0.12.0 present and verified working; Arch's own Discover
  packaging marks the PackageKit-ALPM backend "not recommended".
- **Options**: (a) pyalpm direct; (b) PackageKit; (c) subprocess `pacman -R`.
- **Decision**: pyalpm only. No PackageKit. Subprocess `pacman` is *not* used even as a fallback for transactions (the C API covers removal end-to-end); it is allowed nowhere in v1.
- **Why**: one code path to audit; no daemon semantics mismatch; callback-level progress is real.
- **Security impact**: smaller privileged surface; transactions run inside the single audited helper.
- **UX impact**: truthful progress events from libalpm, not parsed text.

## D2 — Privilege boundary: polkit + D-Bus system service, helper does **only** package transactions

- **Problem**: how to remove packages (a root operation) without a root GUI or a generic root executor.
- **Original assumption (prompt §38–41)**: privileged helper exposing several operations, including deletion of validated user paths.
- **Evidence**: user-owned files (~/.config etc.) are deletable **by the user** — no privilege needed. System files under `/usr`, `/etc`, `/var/lib/pacman` change solely via pacman transactions. Giving the helper a file-deletion verb would enlarge attack surface for a capability the user already has.
- **Options**: (a) helper deletes user files too; (b) helper performs *only* ALPM remove-transactions; user-side deletions of user-owned leftovers run unprivileged in the GUI process.
- **Decision**: **(b).** The D-Bus service exposes exactly one verb family: `RemovePackages` (+ `Ping`/`GetStatus`). polkit action `org.cachyos.uninstall.remove` gates it. User leftover deletion is performed by the user process against paths that survive the central path-policy module and ownership re-check; optional quarantine under `~/.local/share/cachyuninstall/quarantine/`.
- **Why**: the root-side code cannot be abused to delete arbitrary files *by design* — it only speaks to libalpm, which itself enforces ownership/dependency integrity.
- **Security impact**: eliminates the largest class of confused-deputy / arbitrary-delete bugs in the helper.
- **UX impact**: identical visible behavior; authorization is requested exactly once for the system part.

## D3 — Immediate pre-flight revalidation (stale-plan rejection)

- **Problem**: TOCTOU between preview and execution (§43, §79).
- **Decision**: every execution re-derives the plan by re-querying the local DB on the privileged side; the helper compares a **plan digest** (sorted package list + versions + a generation counter the client revalidates). If any target is gone or dependency state changed, the helper aborts with `StalePlan` before touching the DB lock.
- **Why**: libalpm itself re-locks the DB, but the *decision basis* (what the user approved) must match the *system state* at commit time.
- **Security impact**: removes the "approve A, execute B" gap.
- **UX impact**: rare "system changed, please review again" dialog — truthful, not annoying entropy.

## D4 — Progress/callback API: wrap, never guess

- **Problem**: pyalpm C-extension callback signatures must be used exactly.
- **Evidence**: `inspect.signature` cannot extract builtin signatures; docs upstream define `eventcb(event, data)`, `questioncb(question)`, `progresscb(target, percent, n, current)`, `logcb(level, msg)`.
- **Decision**: a single `_CallbackBridge` in the helper adapts verified pyalpm callbacks to internal typed events; no other module touches pyalpm callbacks. Unit-tested against the live binding (read-only init) on CI/dev machines, with a fake-harness mirror for pure logic.
- **Why**: one adapter = one place to be wrong.

## D5 — Cancellation: honest semantics

- **Problem**: §37 forbids promising rollback libalpm cannot guarantee.
- **Decision**: cancellation is offered **before commit** and *during* transaction as best-effort `Transaction.interrupt()` with the label "Stop — the current package step may not be reversible". Filesystem cleanup is cancelled cooperatively between items only.
- **UX impact**: the cancel button is honest about mid-transaction limits.

## D6 — Leftover detection: rule registry + ownership oracle

- **Decision**: candidates come only from versioned rules (`RULE-*`, `docs/LEFTOVER_DETECTION.md`), each yields typed evidence; the ownership oracle (local DB file lists) always has veto power → `PROTECTED`. Confidence ∈ {HIGH, MEDIUM, LOW, PROTECTED}. Low-confidence candidates are hidden by default and never auto-selected.
- **Why**: §55–58; false negatives over false positives (§3).

## D7 — Flatpak: provider present, degrades to "unavailable"

- **Evidence**: flatpak is not installed on the dev host (RECON §6).
- **Decision**: provider checks `flatpak` binary + `org.freedesktop.Flatpak` D-Bus name; if absent, the provider reports `unavailable` and UI hides Flatpak rows without errors. Execution uses Flatpak's own CLI (`flatpak uninstall --delete-data` for user scope) — never manual `~/.var/app` deletion in v1 (§69).

## D8 — AppImage/manual: detection only in v1, no removal verb

- **Decision**: v1 surfaces Manual/AppImage installations for *inspection* with confidence labels; removal requires the user to act (context → open location). This avoids inventing ownership semantics we cannot verify (§74, §150–151). Listed as a deliberate v1 boundary in REQUIREMENTS.

## D9 — Configuration default: keep

- **Decision**: preview defaults to "Keep configuration"; cache/data selection is explicit (§64, §95).

## D10 — No bundled Python runtime; deps via pacman

- **Decision**: per §12, PKGBUILD declares `python-pyqt6`, `pyalpm`, `polkit`, `dbus`, `python-dbus`. The `.venv` used during development is never packaged.

## D11 — File-size accounting

- **Decision**: `isize` from package metadata for packages; for leftover candidates, apparent size via `stat.st_blocks*512` (allocated) and human label "disk usage"; sparse/hardlink edge cases documented in `docs/LEFTOVER_DETECTION.md`. Never displayed as "exact".

## D12 — Single instance via D-Bus session name + lockfile fallback

- **Decision**: try acquiring a well-known *session* bus name; if unavailable, activate existing window. Lockfile fallback for sessions without D-Bus.

## D13 — History/journal: SQLite

- **Decision**: `~/.local/share/cachyuninstall/history.db`, SQLite via stdlib `sqlite3`. Justified: crash-safe journaling requirements (§186–187) beat JSON-append. No file contents, no secrets logged.

## D14 — Dev-environment python ≥ runtime floor

- **Decision**: code targets **3.11+** syntax/typing only (per spec), CI additionally tests on the system 3.14 interpreter. No `tomllib`-optional gymnastics are needed (we read TOML only in tooling, never at runtime).

## D15 — Themes: embedded source-of-truth, files as generated mirrors

- **Problem**: spec asks for `resources/themes/{dark,light,breeze}.qss` files; the running app needs them packaged or embedded.
- **Decision**: themes are single-sourced as constants in `ui/theme.py`; the
  files in `resources/themes/` are generated mirrors, kept byte-identical by
  `tests/unit/test_theme.py`. A separate breeze.qss was **not** created — our
  dark/light palettes *are* the breeze-inspired set; a third name with
  identical content would be a fake feature. Packaging installs the Python
  module; no QSS file lookup is needed at runtime.
- **Why**: zero divergence risk, zero path-lookup complexity.

## D16 — Origin classification follows pacman's repo precedence

- **Problem**: CachyOS overlay repos (cachyos-v3 etc.) provide rebuilds of
  core/extra packages, so sync-name matching is ambiguous.
- **Decision**: first sync db in pacman.conf order that provides a package
  wins — mirroring pacman's own precedence. Verified on the dev host:
  glibc → `cachyos-v3` (correct), "foreign" only for genuinely foreign
  packages (7zip-bin packages installed outside repos etc.).
- **Why**: honest origin labels; never reassigned as "AUR" (§24).

## D18 — Two-phase startup (measured, not aspirational)

- **Problem**: spec target `<600 ms` cold-to-interactive. Measured on the dev
  host: full enumeration with origins = ~1.5 s (per-package file lists +
  reverse-dep computation dominate; profiled: files 171 ms, required_by
  194 ms, syncdb probing ~700 ms across 7 repos).
- **Decision**: phase 1 paints the table from a *light* local enumeration
  (~113 ms; origins honest-UNKNOWN, display names = package name, no icons);
  phase 2 builds full records + identity graph in a worker and swaps rows in;
  the ownership index (~6.6 s) is never built at startup — only inside
  analysis workers (D3 means it is also fresher).
- **Why**: targets must be met by engineering, not by faking progress (§83).

## D17 — Flatpak removal via curated CLI argv (v1)

- **Problem**: helper must not execute arbitrary commands; Flatpak removal
  is not an ALPM concern.
- **Decision**: Flatpak uninstalls run as the invoking user via structured
  argv `flatpak uninstall [--user] --delete-data -y <id>` from the GUI tier
  (user-scope Flatpaks are user-removable; system scope goes through its own
  polkit), never through the privileged helper. `--delete-data` uses
  Flatpak's own tracking rather than manual `~/.var/app` deletion (§69).
- **Security impact**: zero expansion of the root helper.

## D19 — Orphans tab is filled only from full-detail data (§276/§278)

- **Problem**: `load_orphans()` ran at boot from the *light* package
  enumeration, which skips reverse-dependency computation — so
  `is_orphan_hint` (`reason == dependency and not required_by`) reported
  **every** installed-as-dependency package as an orphan. Measured: light
  mode claimed 508 orphans, full detail had 8. The tab was ~99% wrong.
- **Decision**: the orphan tab is never populated from light data. Startup
  leaves it empty until the enrichment lands; after every removal the state
  is re-read from the DB (`MainWindow.refresh_state()`, the same pipeline
  as startup enrichment) so newly-orphaned dependencies appear and removed
  packages disappear — filtering the old snapshot is insufficient because
  `required_by` of *other* packages changes too.
- **Why**: a safety tool must not accuse500 packages of being junk;
  false positives here violate §3 exactly like the scanner would.

## D20 — Helper unit must not use ProtectSystem=strict; backend fails loudly

- **Problem** (found by physical QA): with `ProtectSystem=strict` +
  `ReadWritePaths=/var/lib/pacman …`, libalpm could not unlink anything
  under the read-only root — yet `commit()` still succeeded (DB entry
  removed, files kept, level-1 errors only *logged*), so the helper
  reported success while every installed file survived.
- **Decision**: (1) the unit no longer uses `ProtectSystem`/`ReadWritePaths`
  — unlinking package files anywhere is the helper's job; scope is enforced
  by HelperCore policy + polkit. (2) `AlpmBackend.remove()` collects every
  `ALPM_LOG_ERROR` during the transaction and raises `TransactionFailed`
  if any appeared, so a partial removal is reported, never "successful".
- **Verification**: A/B physical test — old unit + new detection →
  `error: libalpm reported errors during removal` (rc=1, files kept, no
  silent lie); fixed unit → `removed: gedit`, rc=0, 0 of 1389 package
  files remain.

## D21 — Progress signal member is `progressed` (introspection-verified)

- **Problem**: the client subscribed to D-Bus member `Progress`, but Qt
  exports the adaptor's Qt signal verbatim — `busctl introspect` shows
  `.progressed signal ssiiis`. Match rules are not validated, so the wrong
  name silently delivered **zero** events (the GUI progress dialog never
  received a single update).
- **Decision**: subscribe to the exact member `progressed`; both ends stay
  under our control and the name is pinned by the physical introspection
  evidence recorded in QA.
- **Verification**: GUI harness — progress dialog now shows real stage
  text and a bar that reaches 100 during a physical removal.

## D22 — Screenshots: real captured PNGs, referenced by metainfo

- **Problem**: `<screenshots>` in the AppStream metainfo was empty.
- **Decision**: ship the offscreen-captured GUI PNGs under
  `docs/screenshots/` and reference three of them (main window, preview,
  result) from `data/cachyuninstall.metainfo.xml` via the repository raw
  URLs. `appstreamcli validate --no-net` passes (0 warnings, 0 errors).
- **Why**: screenshots must be genuine captures of the certified build —
  never generated marketing images.

## D23 — Package certification fixes (namcap + self-uninstall)

- **Problem**: the first `makepkg` → `pacman -U` → `pacman -R` cycle found
  three packaging defects: namcap **E-level** error (icon installed under
  `usr/share/icons/hicolor/...` but `hicolor-icon-theme` not declared);
  the D-Bus policy conf lived in the deprecated `/etc/dbus-1/system.d`
  (packages belong in `/usr/share/dbus-1/system.d`); and `pacman -R` left
  the helper **daemon running** (unit file deleted, process not stopped) —
  a stray `/var/tmp/systemd-private-...-cachyuninstall-helper.service-*`
  directory remained after removal.
- **Decision**: (1) add `hicolor-icon-theme` to `depends`; (2) install the
  conf to `/usr/share/dbus-1/system.d` (dbus reloads via the package hook);
  (3) `cachyuninstall.install post_remove()` now does
  `systemctl stop cachyuninstall-helper.service` + `daemon-reload`
  (guarded, best-effort) so the privileged daemon never outlives its unit
  file.
- **Evidence** (physical, container): `makepkg -f` → `check()` **103
  tests passed**, package built; `pacman -U` → helper `active`, D-Bus
  policy loaded (garbage call → `protocol-error`), `--list` 541 rows;
  `pacman -R` → zero stray files among 166 tracked entries (runtime
  `__pycache__` cleaned by Arch's pycache hook), **no helper process**, no
  `/var/tmp` private dir, `find /usr /etc /var -name '*cachyuninstall*'`
  → only shared hierarchy dirs; `~/.local/share/cachyuninstall` (documented
  user data) remains; reinstall → helper `active`, policy enforced.
  namcap after fixes: no E-level findings (remaining W = module false
  positives + `polkit`/`dbus` "may not be needed" + .install hook notices).

## D24 — Flatpak physical certification (QA M): three defects found + session-bus requirement

Physical probes against a simultaneous system+user install of
`org.gnome.Calculator` (disposable container) found three real defects:

1. **Missing scope pin (hang, not error)** — `build_uninstall_argv` emitted no
   scope flag for system installs. With the same app id present in the user
   scope too, `flatpak uninstall --delete-data -y <id>` does not fail: it opens
   the *interactive* "Similar installed refs found … Which do you want to use
   (0 to abort)?" prompt (physically reproduced — blocked until the probe
   session was killed), which would hang the GUI's 30-second captured
   subprocess. `info_json` had the same unscoped shape (probe:
   `flatpak info --system` / `--user` both valid; unflagged returns an
   arbitrary match). **Fix**: both builders always pin `--system`/`--user`;
   `tests/unit/test_flatpak_provider.py` pins the exact argv.
2. **Non-ALPM rows dropped / not refreshed** — `refresh_state.read` re-listed
   pacman rows only, so Flatpak and Manual rows would vanish at enrichment,
   Ctrl+R and post-removal; `_uninstall_flatpak` also never refreshed the
   table after success (stale-list class of D19/§276). **Fix**: read() merges
   all three providers; flatpak success records history, then refreshes.
3. **`replace_rows` froze the boot snapshot** — it re-appended the *old*
   non-pacman rows (`others = [i for i in self._installations …]`) and
   discarded the freshly listed ones: a removed Flatpak row resurrected on
   every refresh, and non-ALPM rows doubled each cycle (the harness's
   dict-keyed id checks had masked 545 vs 543). **Fix**: wholesale replace —
   its single caller (`refresh_state.apply`) now supplies the full merged set.

**Environment requirement**: flatpak's post-uninstall session step fails with
`error: Cannot autolaunch D-Bus without X11 $DISPLAY` when no session bus
exists — rc=1 *after* a fully successful removal (physically observed; the
app fail-loudly reported flatpak's rc=1, which is the correct behavior).
Flatpak flows are therefore exercised under `dbus-run-session`, matching every
real desktop where `DBUS_SESSION_BUS_ADDRESS` is always set.

**Evidence**: harness #3 `_gui_tests3.py` **21/21 PASS** (both scope cycles,
scope-named confirm dialogs, `--delete-data`, history scope details, pacman DB
541→541, duplicate-free 543-row table, `org.gnome.Platform` runtimes untouched
after app removal), screenshots 14–17 + 20, `gui-qa3-results.json`,
probe transcript `docs/qa/flatpak-scope-probe.txt`.

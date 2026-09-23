# REQUIREMENTS (v1)

Derived from the product mission (`README.md`) and decisions (`DECISIONS.md`).
Statuses: [ ] planned, [x] implemented-and-tested.

## R1 Core package operations (pacman/libalpm)
- [x] Enumerate installed packages via pyalpm (never by parsing `pacman -Q`).
- [x] Full metadata snapshot: name, version, desc, repo/origin, size, install date,
  reason (explicit/dependency), groups, deps, optdepends, required-by, files, backup files, licenses, url.
- [x] Origin classification: official repo vs CachyOS repos vs foreign (never auto-labelled "AUR").
- [x] Dependency analysis: forward deps, reverse deps, orphan detection, shared-dependency protection.
- [x] Removal planning (typed plan, dry-run first, cascade = only packages that become orphans *by the user's explicit choice*).
- [x] Removal execution inside the privileged helper via libalpm transactions with real event/progress callbacks.
- [x] Post-removal verification against a fresh local-DB handle.

## R2 Leftover analysis
- [x] Identity graph: package name ↔ desktop entry ↔ Exec binary ↔ AppID ↔ icon.
- [x] XDG-targeted scanning (config/cache/data/state/runtime-artifacts), not whole-home sweeps.
- [x] Evidence-tagged candidates; confidence {HIGH, MEDIUM, LOW, PROTECTED}.
- [x] Ownership oracle: any path owned by *any* installed package = PROTECTED, always.
- [x] Central path policy: reject system roots, symlink traversal, escapes; fd-based validation where deletion runs.
- [x] Low-confidence hidden by default; config kept by default.
- [x] Optional quarantine with manifest, restore, retention.

## R3 Privilege & security
- [x] GUI runs unprivileged. Never `sudo cachyuninstall`, never root GUI.
- [x] Helper = D-Bus system service authorized by polkit (`org.cachyos.uninstall.remove`).
- [x] Helper verbs: package removal only (D2). Strictly-typed, versioned protocol; no arbitrary paths/commands.
- [x] Pre-execution stale-plan revalidation (D3).
- [x] Structured errors; denial aborts cleanly.
- [x] No shell anywhere (`shell=False`, explicit arg vectors) — enforced by lint+tests.

## R4 UX (Qt6 Widgets)
- [x] Master-detail: searchable/sortable application table; details panel (deps, required-by, files, cleanup analysis).
- [x] Preview dialog = signature screen: REMOVE / KEEP / USER DATA / UNCERTAIN / PROTECTED + sizes + per-item reasons.
- [x] Truthful progress (libalpm events), honest cancellation semantics (D5).
- [x] Empty states, origin badges, running-indicator, orphan view, cleanup view.
- [x] Dark/light QSS themes; follows system palette by default.
- [x] Keyboard-first (`/` search, Delete, Esc, Ctrl+R refresh, Ctrl+, settings).

## R5 Providers
- [x] pacman (full).
- [x] Flatpak: detection + listing + uninstall via flatpak CLI when available; clean `unavailable` state when not (D7).
- [x] AppImage/Manual: discovery + inspection only; no removal verb in v1 (D8).

## R6 CLI
- [x] `--list`, `--orphans`, `--dry-run PKG`, `--leftovers PKG`, `--json`.
- [x] Removal requires `--remove` + confirmation or `--yes`; never positional-destroy.

## R7 Persistence
- [x] Settings (`~/.config/cachyuninstall/`).
- [x] History + transaction journal (`~/.local/share/cachyuninstall/`, SQLite, D13).
- [x] Rotating logs; no secrets, no file contents.

## R8 Packaging & docs
- [x] PKGBUILD, .SRCINFO, install script, desktop file, AppStream metainfo, icon, polkit policy, D-Bus service config.
- [x] README, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, ARCHITECTURE, LEFTOVER_DETECTION, PROVIDERS, PACKAGING, TESTING, DEVELOPMENT, QA_MANUAL, DECISIONS, RECON.

## R9 Quality gates
- [x] ruff clean, mypy strict clean on `src/`.
- [x] Unit + property (hypothesis) + security tests; fake-ALPM harness; read-only real-DB integration tests.
- [x] pytest-qt UI tests (offscreen).
- [x] No stub features; every shipped path tested.

## Explicitly out of scope (v1)
- AppImage/manual installation *removal* (D8).
- Package install/upgrade, AUR builds/reinstall.
- Package cache cleaning, generic "system cleaner" features, any memory/"optimizer" features.
- Telemetry, accounts, network use for core flows.

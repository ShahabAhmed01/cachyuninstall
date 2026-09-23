# Changelog

All notable changes to CachyUninstall are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
the project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-09-23

First release.

### Added

- Qt6 Widgets GUI: application table (search/sort/filter), details panel
  (dependencies, reverse deps, files, backup files, raw metadata), orphan tab,
  cleanup tab, history tab. Dark/light Breeze-inspired themes.
- Removal planner with blocked-removal explanations, shared-dependency
  protection and explicit opt-in removal of becoming-orphan dependencies.
- Preview dialog (REMOVE / orphans / KEEP / USER DATA / PROTECTED), with
  reasons and sizes; configuration kept by default (D9).
- Privilege boundary: polkit + D-Bus system helper whose only verb runs
  libalpm removal transactions; strict versioned JSON protocol, generation +
  digest staleness rejection (D2/D3).
- Leftover scanner: rule registry, identity graph (desktop entries, binaries,
  icons), ownership veto, cross-identity sharing protection, size measurement.
- fd-based, symlink-safe user-file cleanup with identity re-verification;
  optional quarantine with manifest and restore.
- SQLite history + crash journal (D13); settings in `~/.config`.
- CLI: `--list`, `--orphans`, `--dry-run`, `--leftovers`, `--remove`
  (explicit + confirm), `--json`.
- Flatpak provider (discovery + `flatpak uninstall --delete-data` when
  available), manual/AppImage inspection.
- Tests: unit, property (hypothesis), security, UI (offscreen), read-only
  integration against the live package DB.
- Packaging: PKGBUILD, .SRCINFO, install script, desktop file, AppStream
  metainfo, icon, polkit policy, D-Bus service activation + systemd unit.

### Notable decisions

See `docs/DECISIONS.md` for the full record (pyalpm-only transactions,
helper verb minimalism, honest cancellation, origin classification priority,
theme single-source, and more).

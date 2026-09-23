# TESTING

## Suites

| Suite | Location | Scope |
|---|---|---|
| unit | `tests/unit/` | planner, paths, leftovers, identity, protocol, helper core, session mapping |
| property | `tests/property/` | hypothesis invariants (owned-paths-always-protected, etc.) |
| security | `tests/security/` | traversal, symlink escape, stale plan, desktop-Exec abuse, ownership protection |
| ui | `tests/ui/` | model/filter, preview defaults — offscreen via `QT_QPA_PLATFORM=offscreen` |
| integration | `tests/integration/` | **read-only** against the real local DB; skipped when `pyalpm` absent |

## Fake harness (§125–126)

`tests/harness/fake_alpm.py` provides:
* `make_record(...)` — domain-level worlds (A/B/C/D/E/H...)
* `fake_handle_factory(...)` — pyalpm-facade for `AlpmSession` tests.

Worlds: single / shared-dependency / orphan-chain / blocked / foreign /
modified-config. Planner tests prove: no silent cascade, orphans offered
opt-in only, blocked packages raise with the blocking reverse-deps, batch
removal of confederated packages allowed.

## Running

```bash
python -m pytest tests/unit tests/security tests/property   # pure logic
QT_QPA_PLATFORM=offscreen python -m pytest tests/ui          # widgets
python -m pytest tests/integration                           # needs system pyalpm
scripts/validate-release.sh                                  # everything + gates
```

## Invariants under test

* The scanner NEVER emits a non-PROTECTED candidate owned by a package
  (property test + explicit unit test).
* Deletion follows `dev+ino` — identity flip ⇒ `FileChanged`, nothing removed.
* Symlink deletion unlinks; never traverses (tested with a target sentinel).
* Protocol rejects malformed/oversized/wrong-field/wrong-op payloads; helper
  denies without authorization; digests pin the approved plan.
* Integration: enumeration >50 packages, `usr/bin/pacman` owned by `pacman`,
  `glibc` removal blocked by planners.

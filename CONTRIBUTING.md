# Contributing

Thank you for improving CachyUninstall.

## Ground rules

1. **Safety > features.** Anything touching deletions, the privilege boundary,
   or protocol validation gets security review before merge.
2. No fake features. If it isn't fully implemented and tested, it isn't shipped.
3. Run the gates: `scripts/validate-release.sh` must pass (ruff, mypy strict,
   pytest incl. property/security/UI suites).

## Getting set up

See `docs/DEVELOPMENT.md` for environment setup on Arch/CachyOS.

## Where to look first

| Area | Docs | Code |
|---|---|---|
| Architecture | `docs/ARCHITECTURE.md` | `src/cachyuninstall/` |
| Decisions | `docs/DECISIONS.md` | — |
| Leftover rules | `docs/LEFTOVER_DETECTION.md` | `core/leftovers.py` |
| Privilege model | `docs/SECURITY.md` | `privilege/` |
| Tests | `docs/TESTING.md` | `tests/` |

## Commit style

Short imperative subject; body explains *why*. Commit config/docs next to the
code they describe. `PROGRESS.md` is updated at phase boundaries.

## Adding features

* New provider: implement `providers/base.py::Provider` + tests + docs entry.
* New leftover rule: see "Adding a leftover rule" in `docs/DEVELOPMENT.md`.
* New helper verb: requires a written threat-model update in
  `docs/SECURITY.md` and new protocol tests, otherwise it will not be merged.

## Security issues

Do not file public issues — see `SECURITY.md`.

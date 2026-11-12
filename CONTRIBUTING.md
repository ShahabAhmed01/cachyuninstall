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

## Issue triage

Labels carry the issue lifecycle. Every label below exists in this
repository (`gh label list`):

| Label | Meaning |
|---|---|
| `needs-triage` | Awaiting maintainer triage |
| `bug` | Something isn't working |
| `enhancement` | New feature or request |
| `documentation` | Improvements or additions to documentation |
| `question` | Further information is requested |
| `accessibility` | Barrier affecting people with disabilities |
| `good first issue` | Good for newcomers |
| `help wanted` | Extra attention is needed |
| `duplicate` | This issue or pull request already exists |
| `invalid` | This doesn't seem right |
| `wontfix` | This will not be worked on |
| `dependencies` | Pull requests that update a dependency |

Lifecycle:

1. **Open.** Every new issue starts with `needs-triage` — unless the
   classification is obvious, in which case a maintainer labels it
   directly. Issues filed from `.github/ISSUE_TEMPLATE/` already arrive
   labeled `bug` or `enhancement`.
2. **Triage.** Reproduce if possible, classify (`bug`, `enhancement`,
   `documentation`, `question`, `accessibility`), set priority in the
   issue body or a comment (this repository has no priority label), then
   remove `needs-triage` — the maintainer who triages the issue is the
   one who removes it. Triage is complete when the label is gone.
3. **Security-sensitive reports are not triaged publicly.** If a report
   touches the privilege boundary or an unpatched vulnerability, stop the
   public thread and redirect the reporter to
   [`SECURITY.md`](SECURITY.md) — GitHub private vulnerability reporting
   (Security tab → "Report a vulnerability") or security@cachyos.org.
4. **Scope gates.** `good first issue` and `help wanted` are applied only
   when the scope is genuinely self-contained — a newcomer should be able
   to land it without architectural context or a security review.
5. **Closing.** `duplicate`, `invalid`, and `wontfix` record why an issue
   is closed. Stale issues get a reminder comment first and are then
   closed; the reporter or a maintainer can reopen them, after which the
   issue re-enters triage with `needs-triage`.

## Security issues

Do not file public issues — see `SECURITY.md`.

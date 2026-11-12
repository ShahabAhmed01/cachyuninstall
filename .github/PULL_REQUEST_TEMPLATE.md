<!--
Thank you for contributing to CachyUninstall. This is a destructive-privilege
application: anything touching deletions, the polkit/D-Bus helper, or the
wire protocol receives security review before merge. Please read
CONTRIBUTING.md and docs/DECISIONS.md before opening a complex PR.
-->

## Summary

Briefly describe what this PR changes and why.

## Motivation

What problem does this solve? Link to the issue if one exists.

## Changes

- Change 1
- Change 2

## Testing performed

- [ ] `scripts/validate-release.sh` passes locally (ruff, format, mypy --strict,
  unit + security + property + UI tests)
- [ ] Integration tests pass on an Arch host with `pyalpm` (or skipped with
  reason)
- [ ] Manual QA checklist from `docs/QA_MANUAL.md` for the affected area
- [ ] New behavior is covered by tests

## Checklist

- [ ] No new user-facing claims without evidence
- [ ] No hardcoded credentials or secrets introduced
- [ ] No unnecessary dependencies added
- [ ] Docs updated next to the code they describe
- [ ] CHANGELOG.md updated (if user-facing)
- [ ] Security-relevant change: reviewed against `docs/SECURITY.md` threat model

## Behavior changes

None / describe any functional behavior change (or state none).

# Security Policy

## Reporting a vulnerability

CachyUninstall is a destructive-privilege application; vulnerabilities are
treated as release blockers.

**Do not open public issues for unpatched high-severity findings.**

Report privately:

* Email: security@cachyos.org (subject: `[cachyuninstall] security report`)
* Or enable private vulnerability reporting on the GitHub repository and use
  "Report a vulnerability".

Include: affected version/commit, reproduction, impact, suggested severity,
and whether you can help verify a fix.

We aim to acknowledge within 72 hours and coordinate disclosure after a fix
or mutually agreed deadline.

## Scope

The threat model and mitigations live in `docs/SECURITY.md`. Particularly in
scope: the privileged D-Bus helper, the wire protocol, package ownership
checks, symlink/TOCTOU handling, polkit policy.

Out of scope: attacks requiring physical access, or issues in upstream
projects (pacman/libalpm, polkit, Qt, D-Bus) themselves — we still appreciate
being informed when our usage pattern is the cause.

## Supported versions

Only the latest release series receives security fixes until 1.x stabilizes.

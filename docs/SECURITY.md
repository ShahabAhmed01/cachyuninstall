# SECURITY MODEL

CachyUninstall is a destructive application. Its security goal:

> Even a fully compromised GUI process must not be able to cause deletion of
> a path the user did not select, or any operation requiring privileges the
> user did not explicitly authorize.

## Threat model

| Threat | Attack surface | Mitigation | Residual risk |
|---|---|---|---|
| Compromised/malicious GUI | sends crafted D-Bus payloads to the helper | helper never trusts input: strict JSON protocol v1, unknown ops/fields rejected, package names grammar-checked (`privilege/protocol.py`); the helper has ONE verb (package removal) — no file paths cross the boundary at all | polkit flaw in auth dialog; accepted residual |
| Arbitrary privileged deletion | "DeletePath(path)" style API | **does not exist** (D2). System files change only via libalpm transactions | none by construction |
| Shell injection via package/app names | metadata → command line | no `shell=True` anywhere (lint-enforced S-rules); all argv are fixed vectors; flatpak CLI receives validated app-ids only | flatpak CLI parsing strings — mitigated by argv form |
| Stale plan execution | system changes between preview and commit | helper recomputes generation (local-db mtime_ns) + plan digest over name lists; mismatch → `StalePlan`, zero actions | mtime granularity (ns) — a same-nanosecond change is not collision-safe in theory, irrelevant in practice |
| TOCTOU on user-file cleanup | symlink swap between scan and delete | dirfd + `O_NOFOLLOW` + lstat dev/inode equality re-checked at delete time (`core/paths.py`), fail closed with `FileChanged` | a same-inode replacement on the same fs is not distinguishable by design |
| Symlink escape | candidate is a symlink into `$HOME/Documents` | symlinks are unlinked, never traversed (identity kind pinned at scan) | none known |
| Package ownership | another package owns the file | ownership oracle has absolute veto → PROTECTED; package db is authoritative for system paths | corrupt local DB → we fail closed (DatabaseUnavailable) |
| Malicious .desktop | hostile `Exec=` | never executed, parsed as text only (§177); tested in `tests/security` | none |
| Malformed D-Bus payloads | fuzzed request bodies | `decode_request` rejects non-objects, wrong types, unknown fields, oversize | covered by unit + fuzz-style parameter tests |
| Authorization denial mid-flow | user cancels polkit prompt | helper checks auth BEFORE any backend state; denial → no-op reply | - |
| GUI crash mid-operation | orphan privileged operations | journal records intent; helper runs one transaction then finishes; on restart, unfinished records are reported, never auto-resumed (§307) | - |
| Lock contention | two package managers concurrently | ALPM lock honored; errno 10 mapped to `PackageManagerBusy`; the lockfile is never deleted | - |

## polkit

* Action `org.cachyos.uninstall.remove`, defaults: `auth_admin` /
  `auth_admin` / `auth_admin_keep`.
* Caller identity = the D-Bus unique connection name of the caller
  (verified mechanism: trailing `QDBusMessage` slot parameter).
* Disabled authorization path: authorizer failure denies by default.

## What the GUI itself can destroy (even if compromised)

Only files that are:
1. inside the allowlisted user XDG subtrees,
2. not symlink escapes / pinned identities,
3. not package-owned,
that the user explicitly selected in the preview. The GUI cannot reach
system paths — all system changes flow through the helper's ALPM verb.

## Systemd-unit hardening (helper)

`NoNewPrivileges`, `ProtectHome=read-only`, `PrivateTmp`,
`RestrictAddressFamilies=AF_UNIX`, D-Bus activation only (no permanent
daemon).

`ProtectSystem=strict` was deliberately **removed** during physical QA: the
helper's entire job is unlinking package files anywhere under `/usr`, `/etc`,
`/opt`, … — with a read-only root, libalpm failed every unlink *yet still
committed the DB removal*, so the helper would report success while keeping
every installed file. Defense in depth replaces it:

* the backend collects every `ALPM_LOG_ERROR` emitted during the
  transaction and fails the reply if any appeared (`privilege/backend.py`) —
  a partial/corrupt removal is reported, never silently "successful";
* scope is enforced by HelperCore policy + polkit, not by filesystem
  sandboxing; there is still no file-path verb on the privileged side.

## Disclosure

See top-level `SECURITY.md` for the reporting policy.

# ARCHITECTURE

CachyUninstall is an unprivileged GUI plus a tiny privileged helper.
The only thing the helper can do is execute libalpm **package removal
transactions** — it has no file-deletion and no command-execution verbs (D2).

```mermaid
flowchart TD
    subgraph User process (unprivileged)
        UI[Qt6 Widgets UI\ntabs: Applications/Orphans/Cleanup/History]
        APP[Orchestration\nMainWindow + workers]
        ID[Identity Engine\n.desktop / binary / icon graph]
        SCAN[Leftover Scanner\nrule registry + ownership oracle]
        PLAN[Removal Planner\ndependency analysis]
        PATH[Path Policy + fd-based delete\nuser-owned files only]
        ALPMR[AlpmSession (pyalpm, READ-ONLY)]
        CLIENT[HelperClient]
    end

    subgraph System bus
        POLKIT[(polkit)]
        DBUS[(D-Bus)]
    end

    subgraph Privileged helper (root, D-Bus activated)
        SVC[QtDBus service adaptor]
        CORE[HelperCore\nauth - protocol - staleness - digest]
        ALPMW[AlpmBackend (pyalpm transactions)]
    end

    UI --> APP
    APP --> PLAN
    APP --> SCAN
    SCAN --> ID
    SCAN --> PATH
    PLAN --> ALPMR
    APP --> CLIENT
    CLIENT -->|structured JSON call| DBUS
    DBUS --> SVC
    SVC --> CORE
    CORE -->|CheckAuthorization| POLKIT
    CORE --> ALPMW
    ALPMW -->|real event callbacks| SVC
    SVC -->|Progress signal| CLIENT
```

## Layers

| Layer | Modules | Rule |
|---|---|---|
| Domain | `core/models.py` | no Qt, no pyalpm, no IO |
| Read adapter | `core/alpm_session.py` | sole pyalpm read surface |
| Analysis | `core/planner.py`, `core/identity.py`, `core/leftovers.py`, `core/ownership.py`, `core/paths.py`, `core/process.py` | pure/testable |
| Execution (user) | `core/filesystem.py` | policy-gated, fd-based, quarantinable |
| Providers | `providers/*` | isolation per technology; availability detection |
| Privilege | `privilege/protocol.py/.helper.py/.backend.py/.service.py/.client.py` | least privilege |
| UI | `ui/*` | widgets only, worker-bound IO |
| Persistence | `persistence/*` | settings JSON, history/journal SQLite |

## Threading

* GUI thread: widgets only.
* `AlpmSession` objects are thread-affine — each worker builds its own.
* The helper executes transactions on one worker thread while a nested
  event loop keeps D-Bus responsive (progress + best-effort cancel).

## Data flows

1. **List**: session → PackageRecord → identity graph → Installation rows.
2. **Preview**: planner.analyze + scanner.scan on a worker; frozen RemovalPlan
   carries `system_generation` (local-db mtime marker).
3. **Execute**: helper re-validates generation + digest + installation of all
   names *before* touching the ALPM lock (D3). Event callbacks stream progress.
4. **Cleanup**: user-side executor re-validates every path via the policy and
   dev/inode identity before deleting; optional quarantine with manifest.
5. **Verify**: fresh session re-read; result = success/partial/failed-safely.

## Why these boundaries

See `docs/DECISIONS.md` — every non-obvious boundary (no PackageKit, helper
verb minimalism, generation+digest staleness, honest cancellation) has a
recorded problem/evidence/options/decision entry.

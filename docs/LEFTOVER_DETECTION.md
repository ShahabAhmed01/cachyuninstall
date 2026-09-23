# LEFTOVER DETECTION

The leftover engine is the product's differentiator and its largest risk
surface. Design mandate (§3): **false negatives are fine; false positives
are not.**

## Pipeline

```
known identity (package name / desktop ids / executables / icons)
        ↓
targeted rules over defined locations only (never whole-home sweeps)
        ↓
evidence: category + reason + rule id
        ↓
ownership oracle (any installed package owning it?) ──yes── PROTECTED
        ↓ no
identity sharing (another installed identity matches this token?) ──yes── PROTECTED
        ↓ no
confidence = HIGH (exact package name | desktop-id rule) / MEDIUM
        ↓
human review (never auto-selected unless explicitly enabled)
```

## Standard Token-Based Rules (every rule is an object with tests)

| Rule ID | Location | Match | Base confidence |
|---|---|---|---|
| `RULE-XDG-CONFIG` | `~/.config/<token>` | exact identity token | package-name==HIGH else MEDIUM |
| `RULE-XDG-CACHE` | `~/.cache/<token>` | exact identity token | MEDIUM/HIGH |
| `RULE-XDG-DATA` | `~/.local/share/<token>` | exact identity token | MEDIUM/HIGH |
| `RULE-XDG-STATE` | `~/.local/state/<token>` | exact identity token | MEDIUM/HIGH |
| `RULE-AUTOSTART` | `~/.config/autostart/<desktop-id>.desktop` | exact desktop id | HIGH |
| `RULE-USER-DESKTOP` | `~/.local/share/applications/<desktop-id>.desktop` | exact desktop id | HIGH |
| `RULE-SYSTEMD-USER` | `~/.config/systemd/user/<desktop-id>.{service,timer,socket,path}` | exact desktop id | HIGH |

Tokens per identity: package name, desktop ids, desktop-id tails
(`org.mozilla.firefox` → `firefox`), executables. All compared lowercase,
exact-match against directory *names* — no substring/glob matching
(name-substring matching is where accidental deletions come from).

## Evidence-Backed Application Data Rules

For applications whose data locations don't follow the simple token-matching
pattern (e.g., Firefox stores data in `~/.mozilla/firefox/` not
`~/.local/share/firefox/`), we provide **evidence-backed application data rules**.

Each rule is an `AppDataRule` object with:
- **Rule ID**: unique identifier (e.g., `RULE-APPDATA-FIREFOX-PROFILE`)
- **Application IDs**: package names or desktop IDs the rule applies to
- **Category**: leftover category
- **Base paths**: directories to search under (relative to `$HOME`)
- **Path pattern**: function yielding candidate paths under each base
- **Evidence**: human-readable explanation of why this location belongs to the application
- **Verification** (optional): function returning `(matches, detail)` for additional confidence
- **Base confidence**: confidence when verification not run or inconclusive
- **Verified confidence**: confidence when verification passes

### Implemented Rules

| Rule ID | Application | Location | Verification | Base Conf. | Verified Conf. |
|---|---|---|---|---|---|
| `RULE-APPDATA-FIREFOX-PROFILE` | Firefox (`firefox`, `org.mozilla.firefox`, `mozilla-firefox`) | `~/.mozilla/firefox/<profile>/` | Profile markers (prefs.js, cert9.db, key4.db, places.sqlite, profiles.ini) | MEDIUM | HIGH |

### Rule Design Principles

1. **Evidence-based**: Each rule documents *why* the location belongs to the application
2. **Verifiable**: Optional verification function checks for application-specific markers
3. **Defensive**: Ownership and sharing vetoes still apply
4. **Tested**: Every rule has positive, negative, ownership, sharing, and verification tests
5. **Versioned**: Rules are part of the codebase, not downloaded at runtime

### Confidence Model for App Data Rules

- **BASE_CONFIDENCE** (MEDIUM): Known location exists, but no application-specific verification
- **VERIFIED_CONFIDENCE** (HIGH): Verification function confirms application-specific markers

## Vetoes (checked for every candidate, twice)

1. Path policy allowlist (`core/paths.py`).
2. Package ownership (`core/ownership.py`) — absolute.
3. Cross-identity sharing — protected with an explanation.

## Confidence language in the UI

* HIGH/MEDIUM shown for selection with explicit reasons.
* LOW exists in the model but is hidden by default (§221).
* PROTECTED is informational and cannot be selected (§222).

## Size accounting (D11)

Sizes are allocated bytes (`st_blocks * 512`), labeled as such. Apparent vs
allocated is never mixed; sparse files therefore report low, accurately for
disk pressure purposes.

## Known limitations (documented to users, §310)

* Heuristic-free discovery means an app storing data under a *non-identity*
  directory name is invisible. We accept that gap rather than guess.
* `/etc`, `/var` are never scanned for leftovers in v1 — config survivors are
  the package system's domain (pacman's `.pacsave`) and remain visible in the
  package's file/backup lists.
* Firefox data in `~/.mozilla/firefox` only detected when Firefox is installed
  via pacman (identity must exist in local DB).
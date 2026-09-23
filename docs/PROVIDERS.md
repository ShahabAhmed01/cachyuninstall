# PROVIDERS

Providers isolate installation technologies. Each reports availability
independently; a missing technology never blocks the rest of the app
(§8, D7).

## Provider matrix (v1)

| Provider | Discovery | Inspection | Removal | Data handling |
|---|---|---|---|---|
| pacman | local ALPM DB | full metadata, deps, files, ownership, reverse deps | libalpm transaction in the privileged helper (polkit) | leftover scanner + quarantine |
| flatpak | `flatpak list --app ...` (argv, no shell) | app id, name, version, scope | `flatpak uninstall --delete-data` via CLI when available | Flatpak-native `--delete-data` (§69) |
| manual/AppImage | `~/Applications`, `~/Apps`, `~/Downloads`, `~/.local/bin` + user desktop entries | display only | **not offered in v1 (D8)** | never touched |

## Contract

```python
class Provider(Protocol):
    kind: ProviderKind
    def is_available(self) -> bool: ...
    def list_installations(self) -> list[Installation]: ...
```

Rules for provider implementations:

1. `is_available()` must be cheap and side-effect free; if False, the
   provider contributes zero rows and no error UI.
2. `list_installations()` must not execute discovered files (AppImages are
   artifacts, not commands — §176).
3. Never infer AUR for pacman packages (§24): a foreign package is labelled
   exactly that. AUR is a *source*, not installed state (§71).
4. Removing pacman packages must be 100 % pyalpm (D1) — no `pacman` argv.

## Detection (§8)

| Capability | Source |
|---|---|
| distro | `/etc/os-release` (`ID`, `ID_LIKE`) — `/etc/cachyos-release` is **not** assumed |
| package DB | pyalpm handle construction |
| session | `XDG_SESSION_TYPE` / `XDG_CURRENT_DESKTOP` |
| flatpak | `shutil.which("flatpak")` |
| AUR helpers | PATH probe (`shelly`, `paru`, `yay`, ...); informational only |

## Why Flatpak via CLI and not libflatpak/D-Bus in v1

`libflatpak` requires GObject bindings (python-gobject is not assumed
present) and the C side wraps the same operations. The CLI is the stable,
documented interface; argv vectors avoid shell semantics entirely. If
Flatpak matures a stable non-GObject binding this decision is revisitable
(tracked in PROGRESS.md).

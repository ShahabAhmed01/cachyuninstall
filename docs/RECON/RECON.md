# RECON — Environment & API Verification

Date: 2026-09-22. All findings below were verified by direct inspection of the
target machine (the development host) and by probing the live pyalpm/dbus APIs.

## 1. Host system

| Item | Verified value |
|---|---|
| Distribution | CachyOS (`ID=cachyos`, `ID_LIKE=arch`, rolling) |
| `/etc/cachyos-release` | **not present** on this install — detection must fall back to `/etc/os-release` |
| Repositories configured | `cachyos-v3`, `cachyos-extra-v3`, `cachyos-core-v3`, `cachyos`, `core`, `extra`, `multilib` |
| Desktop | KDE Plasma, Wayland (`XDG_SESSION_TYPE=wayland`, `XDG_CURRENT_DESKTOP=KDE`) |
| Kernel/session tools | systemd user session present |

## 2. Language / toolchain

| Tool | Version |
|---|---|
| Python (system) | **3.14.7** (target floor stays 3.11; code must not use >3.13-only idioms carelessly, but CI targets 3.14) |
| gcc | 16.2.1 |
| make | 4.4.1 |
| git | 2.55.0 |

## 3. Package management stack (verified live)

| Component | Verified |
|---|---|
| pacman | 7.1.0 |
| libalpm | 16.0.1 |
| pyalpm | **0.12.0-1.1** — installed; `python-alpm` (the unrelated Rust project) is not installed |
| `pyalpm.Handle('/', '/var/lib/pacman/')` | works unprivileged for reads |
| Local DB | 1411 packages readable |
| `Package` attributes | `name, version, desc, arch, url, licenses, groups, depends, optdepends, makedepends, checkdepends, conflicts, provides, replaces, files, backup, installdate, packager, isize, reason, base, has_scriptlet, compute_requiredby(), compute_optionalfor()` |
| Reason constants | `PYG_REASON` → `pyalpm.PKG_REASON_EXPLICIT = 0`, `pyalpm.PKG_REASON_DEPEND = 1` |
| `Handle` capabilities | `init_transaction`, `register_syncdb`, `load_pkg`, `lockfile`, `eventcb/progresscb/questioncb/logcb/dlcb`, `get_localdb`, `get_syncdbs` |
| `Transaction` | `add_pkg`, `remove_pkg`, `prepare`, `sysupgrade`, `commit`, `interrupt`, `release`, `to_add`, `to_remove`, `flags` |

Exact callback *signatures* are defined by the pyalpm C extension; they are
exercised only behind an abstraction layer in `core/alpm_session.py` and in the
privileged helper, never guessed in calling code. Callback semantics are
documented in `docs/DECISIONS.md` (D4).

## 4. Privilege / IPC stack

| Component | Verified |
|---|---|
| polkit | 127 (`pkcheck` 127) |
| polkit action dir | `/usr/share/polkit-1/actions/` (system policy present, incl. `com.shellyorg.shelly.policy`) |
| D-Bus | 1.16.2, system + session bus present |
| dbus-python | `python-dbus` 1.4.0 installed |

Decision impact: the privileged helper uses **polkit + a D-Bus–activatable
system service** with a structured, versioned protocol — no `sudo` wrapping, no
root GUI. See `docs/DECISIONS.md` (D2).

## 5. Qt / GUI

| Component | Verified |
|---|---|
| Qt 6 | 6.11.2 (`qt6-base`) installed |
| PyQt6 | **not installed system-wide on this dev host** → development virtualenv `.venv/` (pip, used *only* for the dev loop; runtime packaging depends on `python-pyqt6` from repos) |
| Qt tools | `qmake6`, Qt tools in `/usr/lib/qt6/bin/` |

## 6. Optional providers

| Provider | State on dev host |
|---|---|
| Flatpak | **not installed** → provider must degrade to `unavailable` cleanly (runtime detection, no hard dependency) |
| AUR helpers | `shelly` 3.1.4 installed; `paru`/`yay`/`pikaur` absent → helper detection is dynamic; core removal never requires a helper |
| AppStream | `appstream` 1.2.0 + `appstreamcli` present → metadata enrichment reads the system AppStream cache, never the network |

## 7. Development tooling (virtualenv)

`pytest`, `hypothesis`, `ruff`, `mypy`, `pytest-qt`, `PyQt6` are installed into
`.venv/` (development only). Runtime dependencies for packaging are Arch
packages only: `python`, `python-pyqt6`, `pyalpm`, `polkit`, `dbus`,
`python-dbus`.

## 8. Security-relevant host facts

- `sudo` requires a password on this host (no passwordless sudo assumed anywhere).
- No `/etc/cachyos-release`: distro detection must be capability-based.
- `/var/lib/pacman/local` is readable unprivileged (normal on Arch) — read-only
  inspection needs no privilege; only transactions do.

## 9. Existing-tool survey (positioning)

Based on upstream documentation and the local install:

- **Discover** (KDE): multi-source *installer/store*; its PackageKit-arch backend
  is explicitly flagged "not recommended" upstream for Arch repo packages.
  Removal exists but leftover analysis is not a feature.
- **pamac / octopi**: package-manager frontends; no evidence-based leftover
  analysis with ownership protection.
- **bauh**: multi-format manager (Arch/AUR, Flatpak, AppImage, web); breadth-first,
  cleanup/safety analysis is not its center of gravity.
- **bleachbit-style cleaners**: file-based, not package-database-integrated.

Gap confirmed: no mainstream Arch tool couples **libalpm transactions** with an
**evidence-based, ownership-protected leftover analysis** and a strict
**polkit-mediated privilege boundary**. That is CachyUninstall's center.

# PACKAGING

## Layout installed by the PKGBUILD

```
/usr/bin/cachyuninstall                      (entry point)
/usr/bin/cachyuninstall-helper               (privileged D-Bus service binary)
/usr/lib/python3.X/site-packages/cachyuninstall/…
/usr/share/applications/cachyuninstall.desktop
/usr/share/metainfo/org.cachyos.uninstall.metainfo.xml
/usr/share/icons/hicolor/scalable/apps/cachyuninstall.svg
/usr/share/polkit-1/actions/org.cachyos.uninstall.policy
/usr/share/dbus-1/system-services/org.cachyos.Uninstall.service
/usr/share/dbus-1/system.d/org.cachyos.Uninstall.conf
/usr/lib/systemd/system/cachyuninstall-helper.service
/usr/share/licenses/cachyuninstall/LICENSE
/usr/share/doc/cachyuninstall/SECURITY.md
```

## Build from source

```bash
git clone <repo> && cd cachyuninstall
scripts/mksource.sh           # creates cachyuninstall-<ver>.tar.gz
mkdir -p build-aur
cp PKGBUILD cachyuninstall.install cachyuninstall-<ver>.tar.gz build-aur/
(cd build-aur && makepkg -si)
```

Run `makepkg` in the staging directory, **never in the repository root**:
makepkg extracts into `./src`, which collides with the Python source tree
(the lint gate then scans the extracted copy) and its source symlink lands
inside `src/` where `mksource.sh` would scoop it into the next tarball.

`.SRCINFO` is regenerated at the repo root (`makepkg --printsrcinfo >
.SRCINFO`) — that mode is read-only and creates no build tree.

## Validation

```bash
scripts/validate-release.sh   # lint, mypy, tests, metadata validation
makepkg --printsrcinfo > .SRCINFO
namcap PKGBUILD
```

`.SRCINFO` is regenerated from the PKGBUILD at release time — never hand-edited
into divergence (§121).

## Dependency policy (§123)

Runtime: `python`, `python-pyqt6`, `pyalpm`, `python-dbus`, `polkit`,
`dbus`, `hicolor-icon-theme`. Optional: `flatpak`. Nothing else. Every
dependency earns its slot:

* `pyalpm` — the package engine (D1)
* `python-pyqt6` — GUI + QtDBus service plumbing (D2)
* `python-dbus` — polkit CheckAuthorization structs (PyQt6 QDBusArgument
  cannot demarshal `(bba{ss})`; verified limit)
* `polkit`, `dbus` — the privilege and message infrastructure
* `hicolor-icon-theme` — owns the `usr/share/icons/hicolor/…` hierarchy
  the launcher icon installs into (namcap requires declaring it; D23)

## Self-removal (§305/306)

CachyUninstall is installed like any other package and is removed by pacman:

```bash
pikaur -R cachyuninstall   # or: sudo pacman -R cachyuninstall
```

The app does not perform root-mediated self-deletion while running; its own
entry simply shows "installed via pacman" metadata. User-side state lives in
`~/.config/cachyuninstall`, `~/.local/share/cachyuninstall`,
`~/.cache/cachyuninstall` and its own scanner protects those by policy
(`_PROTECTED_BASENAMES`).

# Maintainer: CachyUninstall contributors
pkgname=cachyuninstall
pkgver=1.0.0
pkgrel=1
pkgdesc="Safe, transparent native uninstaller and leftover analyzer for Arch/CachyOS"
arch=('any')
url="https://github.com/ShahabAhmed01/cachyuninstall"
license=('GPL-3.0-or-later')
depends=(
    'python'
    'python-pyqt6'
    'pyalpm'
    'python-dbus'
    'polkit'
    'dbus'
    'hicolor-icon-theme'
)
makedepends=(
    'python-setuptools'
    'python-build'
    'python-installer'
    'python-wheel'
)
checkdepends=(
    'python-pytest'
    'python-hypothesis'
    'python-pyqt6'
)
optdepends=(
    'flatpak: Flatpak application support'
)
# Development flow: scripts/mksource.sh produces ${pkgname}-${pkgver}.tar.gz
# from the repository. For AUR publication this becomes the tagged tarball URL.
source=("${pkgname}-${pkgver}.tar.gz")
sha256sums=('SKIP')
install=cachyuninstall.install

build() {
    cd "${srcdir}/${pkgname}-${pkgver}"
    python -m build --wheel --no-isolation
}

package() {
    cd "${srcdir}/${pkgname}-${pkgver}"
    python -m installer --destdir="${pkgdir}" dist/*.whl

    # Desktop integration
    install -Dm644 data/cachyuninstall.desktop \
        "${pkgdir}/usr/share/applications/cachyuninstall.desktop"
    install -Dm644 data/cachyuninstall.metainfo.xml \
        "${pkgdir}/usr/share/metainfo/org.cachyos.uninstall.metainfo.xml"
    install -Dm644 data/icons/hicolor/scalable/apps/cachyuninstall.svg \
        "${pkgdir}/usr/share/icons/hicolor/scalable/apps/cachyuninstall.svg"

    # Privilege boundary (D2): polkit policy, D-Bus system service, unit file
    install -Dm644 data/org.cachyos.uninstall.policy \
        "${pkgdir}/usr/share/polkit-1/actions/org.cachyos.uninstall.policy"
    install -Dm644 data/org.cachyos.Uninstall.service \
        "${pkgdir}/usr/share/dbus-1/system-services/org.cachyos.Uninstall.service"
    # dbus reads package policy configs from /usr/share/dbus-1/system.d;
    # /etc/dbus-1/system.d is reserved for local admin overrides (namcap E).
    install -Dm644 data/org.cachyos.Uninstall.conf \
        "${pkgdir}/usr/share/dbus-1/system.d/org.cachyos.Uninstall.conf"
    install -Dm644 data/cachyuninstall-helper.service \
        "${pkgdir}/usr/lib/systemd/system/cachyuninstall-helper.service"

    # License + docs
    install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
    install -Dm644 docs/SECURITY.md "${pkgdir}/usr/share/doc/${pkgname}/SECURITY.md"
}

check() {
    cd "${srcdir}/${pkgname}-${pkgver}"
    # Security + unit suites must pass; UI tests run offscreen.
    QT_QPA_PLATFORM=offscreen python -m pytest tests/unit tests/security tests/property -q
}

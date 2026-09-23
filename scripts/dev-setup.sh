#!/usr/bin/env bash
# Development environment setup for CachyUninstall (arch/CachyOS hosts).
#
# Safe-by-design (§303):
#  - prints exactly what it will install, requires explicit confirmation
#  - uses pacman with --needed (idempotent), never pipes remote scripts
#  - creates a local .venv with --system-site-packages so system pyalpm works
set -euo pipefail

cd "$(dirname "$0")/.."

PACKAGES=(
    python python-pyqt6 pyalpm python-dbus polkit dbus
    python-pytest python-hypothesis python-pytest-qt
    python-build python-installer python-wheel python-setuptools
    base-devel git
)

echo "This will install the following packages (with pacman --needed):"
printf '  %s\n' "${PACKAGES[@]}"
echo
read -r -p "Continue? [y/N] " answer
case "${answer}" in
    y|Y|yes) ;;
    *) echo "Aborted."; exit 1 ;;
esac

sudo pacman -S --needed "${PACKAGES[@]}"

if [[ ! -d .venv ]]; then
    python -m venv --system-site-packages .venv
fi
.venv/bin/pip install --quiet ruff mypy

echo
echo "Done. Activate with: source .venv/bin/activate"
echo "First check: make lint typecheck test  (or scripts/validate-release.sh)"

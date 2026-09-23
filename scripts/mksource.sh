#!/usr/bin/env bash
# Build the source tarball the PKGBUILD expects (scripts referenced from docs).
set -euo pipefail
cd "$(dirname "$0")/.."

PKGVER=$(sed -n 's/^pkgver=//p' PKGBUILD)
PKGNAME=$(sed -n 's/^pkgname=//p' PKGBUILD)
DIR="${PKGNAME}-${PKGVER}"
STAGE="$(mktemp -d)/${DIR}"

mkdir -p "${STAGE}"
cp -a src tests docs data resources scripts \
      pyproject.toml ruff.toml mypy.ini LICENSE README.md SECURITY.md \
      CONTRIBUTING.md CODE_OF_CONDUCT.md CHANGELOG.md PROGRESS.md \
      PKGBUILD cachyuninstall.install "${STAGE}/"

tar -C "${STAGE%/*}" -czf "${DIR}.tar.gz" "${DIR}"
echo "created ${DIR}.tar.gz"

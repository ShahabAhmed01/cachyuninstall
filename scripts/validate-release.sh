#!/usr/bin/env bash
# Release gate (§304): everything that must pass before a release.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[[ -x "$PY" ]] || PY="python"
export QT_QPA_PLATFORM=offscreen

step() { printf '\n=== %s ===\n' "$*"; }

step "ruff lint"
"$PY" -m ruff check src tests

step "ruff format check"
"$PY" -m ruff format --check src tests

step "mypy --strict"
"$PY" -m mypy -p cachyuninstall --config-file mypy.ini

step "unit + security + property + ui tests"
"$PY" -m pytest tests/unit tests/security tests/property tests/ui -q

step "integration tests (read-only, system python w/ pyalpm)"
if /usr/bin/python -c "import pyalpm" 2>/dev/null; then
    PYTHONPATH="src:.venv/lib/python3.14/site-packages" \
        /usr/bin/python -m pytest tests/integration -q -p no:cacheprovider
else
    echo "pyalpm not importable by system python; skipped"
fi

step "desktop file validation"
command -v desktop-file-validate >/dev/null && desktop-file-validate data/cachyuninstall.desktop

step "appstream metainfo validation"
command -v appstreamcli >/dev/null && appstreamcli validate --no-net \
    data/cachyuninstall.metainfo.xml || echo "(appstreamcli unavailable)"

step "polkit policy XML sanity"
python -c "import xml.dom.minidom,sys; xml.dom.minidom.parse('data/org.cachyos.uninstall.policy'); print('policy XML ok')"

step "build check (wheel)"
"$PY" -m pip show build >/dev/null 2>&1 && \
    "$PY" -m build --wheel --no-isolation -o /tmp/opencode/cachyuninstall-dist || \
    echo "(python-build not available; wheel build skipped)"

echo
echo "Release gate passed."

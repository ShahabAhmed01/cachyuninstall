# DEVELOPMENT

## Setup (on Arch/CachyOS)

```bash
scripts/dev-setup.sh          # installs repo packages needed for developmen
python -m venv .venv --system-site-packages   # reuse system pyalpm
.venv/bin/pip install -e '.[dev]' || .venv/bin/pip install pytest hypothesis ruff mypy pytest-qt
```

`pyalpm` is provided by the system (`pacman -S pyalpm`) and only works
against system Python — always develop with `--system-site-packages`.

## Quality loop

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy -p cachyuninstall --config-file mypy.ini
.venv/bin/pytest tests/unit tests/security tests/property tests/ui
QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui
```

Run integration tests with system python so `pyalpm` resolves (they are
read-only). See `scripts/validate-release.sh` for the enforced gate.

## Coding rules that exist for reasons

* **No pyalpm objects leave `core/alpm_session.py`** — the C-extension types
  are intentionally isolated behind dataclasses.
* **No IO on the GUI thread** — `ui/workers.py` `Executor.run` is the only
  bridge; providers and the session run on thread workers.
* **Lazy heavy imports** — pyalpm/PyQt6/dbus are imported inside functions
  (marked PLC0415 in ruff.toml) so the CLI and tests load without them.
* **Domain types are frozen dataclasses** — planning and scanning are pure
  and property-testable.

## Adding a leftover rule (§182)

1. Add a class in `core/leftovers.py` with `RULE_ID`, `CATEGORY`, `discover()`.
2. Register in `ALL_RULES`, add a reason template.
3. Add tests in `tests/unit/test_leftovers.py` covering: matched case,
   sharing case, ownership-veto case.
4. Update this doc table and `docs/LEFTOVER_DETECTION.md`.

## Adding a provider

Implement `providers/base.py::Provider`. Integrate availability probing,
`Installation` rows and — only after a security review — execution verbs
(see `docs/SECURITY.md` threat table first).

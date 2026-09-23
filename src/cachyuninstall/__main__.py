"""Entrypoint: GUI by default; CLI when flags are given."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    cli_flags = {"--list", "--orphans", "--dry-run", "--leftovers", "--remove"}
    if any(arg in cli_flags or arg == "--json" for arg in argv) or "--help" in argv or "-h" in argv:
        from cachyuninstall.cli import run_cli

        return run_cli(argv)
    from cachyuninstall.app import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())

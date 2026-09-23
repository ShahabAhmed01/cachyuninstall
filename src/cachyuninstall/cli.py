"""Headless CLI (§116-117).

Read operations work unprivileged and offline. Removal requires the explicit
`--remove` flag and interactive confirmation (or --yes), and is executed only
through the privileged helper — never directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cachyuninstall.core.models import PackageRecord

from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.errors import CuError
from cachyuninstall.core.identity import Identity, build_identity_index
from cachyuninstall.core.leftovers import LeftoverScanner, ScanContext
from cachyuninstall.core.models import PackageName
from cachyuninstall.core.ownership import DictOwnerIndex, OwnershipOracle
from cachyuninstall.core.paths import PathPolicy
from cachyuninstall.core.planner import RemovalPlanner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cachyuninstall",
        description="Safe uninstall & leftover analysis for Arch/CachyOS.",
    )
    p.add_argument("--list", action="store_true", help="List installed applications")
    p.add_argument("--orphans", action="store_true", help="List orphan packages")
    p.add_argument("--dry-run", metavar="PKG", help="Analyze removal of PKG without changes")
    p.add_argument("--leftovers", metavar="PKG", help="Scan PKG for leftover data")
    p.add_argument("--remove", metavar="PKG", help="Remove PKG via the privileged helper")
    p.add_argument("--yes", action="store_true", help="Do not ask for confirmation (with --remove)")
    p.add_argument("--also-orphans", action="store_true", help="Also remove becoming-orphan deps")
    p.add_argument("--json", action="store_true", help="Machine-readable output")
    return p


def _json_out(obj: object) -> None:
    """JSON output boundary: only dict/list/str/int/Path/Enum values arrive here."""

    def default(o: object) -> str:
        return str(o)  # Enum -> "value".*, Path -> path text

    print(json.dumps(obj, default=default, indent=2, sort_keys=True))


def _print_packages(pkgs: list[PackageRecord], as_json: bool) -> int:
    if as_json:
        _json_out(
            [
                {
                    "name": str(p.name),
                    "version": p.version,
                    "origin": p.origin.value,
                    "size_bytes": p.size_bytes,
                    "reason": p.reason.value,
                }
                for p in pkgs
            ]
        )
    else:
        for p in sorted(pkgs, key=lambda x: x.name):
            print(f"{p.origin.value:<12} {p.name} {p.version}")
    return 0


def _open_session() -> AlpmSession:
    session = AlpmSession()
    session.open()
    return session


def run_cli(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.remove:
            return _cmd_remove(args)
        if args.list:
            return _print_packages(_open_session().packages(), args.json)
        if args.orphans:
            orphans = [p for p in _open_session().packages() if p.is_orphan_hint]
            return _print_packages(orphans, args.json)
        if args.dry_run:
            return _cmd_dry_run(args)
        if args.leftovers:
            return _cmd_leftovers(args)
    except CuError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _build_parser().print_help()
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    session = _open_session()
    return run_remove(args, session.packages(), session)


def _cmd_dry_run(args: argparse.Namespace) -> int:
    session = _open_session()
    planner = RemovalPlanner(session.packages())
    try:
        impact = planner.analyze([PackageName(args.dry_run)])
    except CuError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    blocked = bool(impact.blocked_by)
    if args.json:
        _json_out(
            {
                "targets": list(map(str, impact.requested)),
                "blocked_by": {str(k): list(map(str, v)) for k, v in impact.blocked_by.items()},
                "new_orphans": list(map(str, impact.new_orphans)),
                "kept_shared": {str(k): list(map(str, v)) for k, v in impact.kept_shared.items()},
            }
        )
        return 1 if blocked else 0
    print(f"remove: {', '.join(map(str, impact.requested))}")
    for name, blockers in impact.blocked_by.items():
        print(f"BLOCKED: {name} is required by {', '.join(blockers)}")
    if impact.new_orphans:
        print("would orphan: " + ", ".join(map(str, impact.new_orphans)))
    for name, users in impact.kept_shared.items():
        print(f"kept (shared): {name} <- {', '.join(map(str, users[:4]))}")
    return 1 if blocked else 0


def _cmd_leftovers(args: argparse.Namespace) -> int:
    session = _open_session()
    packages = session.packages()
    identities = build_identity_index(packages)
    name = PackageName(args.leftovers)
    oracle = OwnershipOracle(DictOwnerIndex(session.refresh_owner_index()))
    ctx = ScanContext(
        home=Path.home(),
        identity=identities.get(name, Identity(package=name)),
        other_identities=tuple(i for k, i in identities.items() if k != name),
        oracle=oracle,
    )
    candidates = LeftoverScanner(PathPolicy()).scan(ctx)
    if args.json:
        _json_out(
            [
                {
                    "path": str(c.path),
                    "category": c.category.value,
                    "confidence": c.confidence.value,
                    "rule": c.rule_id,
                    "reason": c.reason,
                    "size_bytes": c.size_bytes,
                }
                for c in candidates
            ]
        )
        return 0
    if not candidates:
        print("No leftovers found.")
        return 0
    for c in candidates:
        print(f"[{c.confidence.value:>9}] {c.category.value:<16} {c.path}")
        print(f"             why: {c.reason}")
    return 0


def run_remove(args: argparse.Namespace, packages: list[PackageRecord], session: AlpmSession) -> int:
    from PyQt6.QtCore import QCoreApplication

    from cachyuninstall.privilege.client import HelperClient

    planner = RemovalPlanner(packages)
    name = PackageName(args.remove)
    try:
        impact = planner.analyze([name])
    except CuError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if impact.blocked_by:
        for pkg, blockers in impact.blocked_by.items():
            print(f"cannot remove {pkg}: required by {', '.join(blockers)}", file=sys.stderr)
        return 1

    cascade = impact.new_orphans if args.also_orphans else ()
    planned = (*impact.requested, *cascade)
    print("Packages to remove: " + ", ".join(map(str, planned)))
    if not args.yes:
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    # QCoreApplication is required by QtDBus but the call below is
    # synchronous (QDBus.CallMode.Block) — never exec() a loop here, or the
    # CLI would hang after the reply already arrived.
    app = QCoreApplication(sys.argv[:1])
    client = HelperClient()
    if not client.is_available():
        print("error: privileged helper is not available (policy not installed?)", file=sys.stderr)
        return 3
    plan = planner.build_plan(
        [name],
        also_remove_new_orphans=bool(args.also_orphans),
        generation=session.generation(),
    )
    reply = client.remove_packages(plan, lambda _r: None, blocking=True)
    del app
    if reply is None:  # defensive: blocking mode must always return a reply
        print("error: no reply from helper", file=sys.stderr)
        return 3
    if reply.ok:
        print("removed: " + ", ".join(map(str, reply.removed)))
        return 0
    print(f"error: {reply.message}", file=sys.stderr)
    return 1

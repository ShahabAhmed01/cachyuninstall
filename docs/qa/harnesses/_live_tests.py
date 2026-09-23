"""TEMPORARY live acceptance tests against the running helper (QA phase).

Subcommands:
  lock <pkg>      - hold db.lck, attempt removal, expect busy failure
  stale <pkg>     - build plan, mutate DB, expect stale-plan rejection
  malformed       - protocol abuse: bad JSON/version/op/name/size
  polkit <pkg>    - send remove as the current (unprivileged) user,
                    expect authorization-denied; package must survive
  ping            - basic liveness
"""

from __future__ import annotations

import glob
import json
import os
import sys

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage

from cachyuninstall import DBUS_NAME, DBUS_PATH
from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.models import PackageName
from cachyuninstall.core.planner import RemovalPlanner
from cachyuninstall.privilege.protocol import encode_request

IFACE = "org.cachyos.Uninstall"


def _call(payload: str, timeout: int = 30000) -> str:
    call = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, IFACE, "Call")
    call.setArguments([payload])
    reply = QDBusConnection.systemBus().call(call, QDBus.CallMode.Block, timeout)
    if reply.errorMessage():
        return f"<dbus-error: {reply.errorMessage()}>"
    args = reply.arguments()
    return str(args[0]) if args else "<empty>"


def _plan_for(target: str):
    session = AlpmSession()
    session.open()
    planner = RemovalPlanner(session.packages())
    plan = planner.build_plan(
        [PackageName(target)], also_remove_new_orphans=False, generation=session.generation()
    )
    return session, plan


def _payload(plan, generation_override=None) -> str:
    payload = {
        "plan_id": plan.plan_id,
        "targets": [str(t) for t in plan.targets],
        "cascade": [str(c) for c in plan.cascade],
        "generation": plan.system_generation if generation_override is None else generation_override,
        "digest": plan.digest(),
    }
    return encode_request("remove_packages", payload)


def cmd_stale(target: str) -> int:
    _, plan = _plan_for(target)
    # generation() = st_mtime_ns of /var/lib/pacman/local — bump THAT (a
    # child dir's mtime is not what the gate reads).
    os.utime("/var/lib/pacman/local", None)
    out = _call(_payload(plan))
    print(out)
    ok = '"stale-plan"' in out
    print("STALE-PLAN REJECTED:", ok)
    return 0 if ok else 1


def cmd_lock(target: str) -> int:
    lock = "/var/lib/pacman/db.lck"
    open(lock, "w").close()
    try:
        _, plan = _plan_for(target)
        out = _call(_payload(plan))
        print(out)
        ok = ("PackageManagerBusy" in out) or ("locked" in out.lower()) or ("busy" in out.lower())
        print("LOCK REFUSED:", ok)
        return 0 if ok else 1
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass


def cmd_malformed() -> int:
    cases = {
        "not-json": "this is not json",
        "wrong-version": json.dumps({"v": 99, "op": "ping", "payload": {}}),
        "unknown-op": json.dumps({"v": 1, "op": "rm_rf", "payload": {}}),
        "unknown-field": json.dumps(
            {"v": 1, "op": "ping", "payload": {}, "extra": 1}
        ),
        "bad-name": json.dumps(
            {
                "v": 1,
                "op": "remove_packages",
                "payload": {
                    "plan_id": "x",
                    "targets": ["../../etc/passwd"],
                    "cascade": [],
                    "generation": 1,
                    "digest": "a" * 64,
                },
            }
        ),
        "long-plan-id": json.dumps(
            {
                "v": 1,
                "op": "remove_packages",
                "payload": {
                    "plan_id": "x" * 100,
                    "targets": ["vim"],
                    "cascade": [],
                    "generation": 1,
                    "digest": "a" * 64,
                },
            }
        ),
        "bad-digest": json.dumps(
            {
                "v": 1,
                "op": "remove_packages",
                "payload": {
                    "plan_id": "x",
                    "targets": ["vim"],
                    "cascade": [],
                    "generation": 1,
                    "digest": "short",
                },
            }
        ),
        "oversized": json.dumps(
            {
                "v": 1,
                "op": "remove_packages",
                "payload": {
                    "plan_id": "x",
                    "targets": ["vim"] * 600,  # > MAX_PACKAGE_NAMES
                    "cascade": [],
                    "generation": 1,
                    "digest": "a" * 64,
                },
            }
        ),
    }
    all_ok = True
    for label, payload in cases.items():
        out = _call(payload, timeout=10000)
        refused = ("protocol-error" in out) or ("dbus-error" in out)
        print(f"{label:<16} -> {out[:100]}  refused={refused}")
        all_ok = all_ok and refused
    alive = _call(json.dumps({"v": 1, "op": "ping", "payload": {}}), timeout=5000)
    healthy = "alive" in alive
    print(f"helper alive after abuse: {healthy} ({alive[:80]})")
    print("MALFORMED SUITE:", all_ok and healthy)
    return 0 if (all_ok and healthy) else 1


def cmd_polkit(target: str) -> int:
    print("caller uid:", os.getuid(), "user:", os.environ.get("USER", "?"))
    _, plan = _plan_for(target)
    out = _call(_payload(plan), timeout=60000)
    print(out)
    denied = "authorization-denied" in out
    print("POLKIT DENIED:", denied)
    # package must still be installed
    session = AlpmSession()
    session.open()
    still = any(str(p.name) == target for p in session.packages())
    print(f"{target} still installed: {still}")
    return 0 if (denied and still) else 1


def cmd_ping() -> int:
    out = _call(json.dumps({"v": 1, "op": "ping", "payload": {}}), timeout=5000)
    print(out)
    return 0 if "alive" in out else 1


def main() -> int:
    QCoreApplication(sys.argv[:1])
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd, *rest = sys.argv[1:]
    if cmd == "stale":
        return cmd_stale(rest[0])
    if cmd == "lock":
        return cmd_lock(rest[0])
    if cmd == "malformed":
        return cmd_malformed()
    if cmd == "polkit":
        return cmd_polkit(rest[0])
    if cmd == "ping":
        return cmd_ping()
    print("unknown cmd", cmd)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

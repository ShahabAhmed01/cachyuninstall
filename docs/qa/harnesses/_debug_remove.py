"""TEMPORARY debug harness: print the raw helper reply for a removal."""

import sys

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage

from cachyuninstall import DBUS_NAME, DBUS_PATH
from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.models import PackageName
from cachyuninstall.core.planner import RemovalPlanner
from cachyuninstall.privilege.protocol import encode_request

_IFACE = "org.cachyos.Uninstall"


def main() -> int:
    app = QCoreApplication(sys.argv[:1])
    target = sys.argv[1]
    session = AlpmSession()
    session.open()
    planner = RemovalPlanner(session.packages())
    name = PackageName(target)
    plan = planner.build_plan(
        [name], also_remove_new_orphans=False, generation=session.generation()
    )
    payload = {
        "plan_id": plan.plan_id,
        "targets": [str(t) for t in plan.targets],
        "cascade": [str(c) for c in plan.cascade],
        "generation": plan.system_generation,
        "digest": plan.digest(),
    }
    msg = encode_request("remove_packages", payload)
    call = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, _IFACE, "Call")
    call.setArguments([msg])
    reply = QDBusConnection.systemBus().call(call, QDBus.CallMode.Block, 300000)
    print("errorMessage:", repr(reply.errorMessage()))
    args = reply.arguments()
    print("n_args:", len(args))
    for i, a in enumerate(args):
        print(f"arg[{i}] type={type(a).__name__} len={len(str(a))}")
        print(f"arg[{i}] first32={str(a)[:32]!r} last16={str(a)[-16:]!r}")
        try:
            import json

            parsed = json.loads(str(a))
            print(f"arg[{i}] json.loads OK: {type(parsed).__name__} keys={sorted(parsed) if isinstance(parsed, dict) else None}")
        except Exception as exc:
            print(f"arg[{i}] json.loads FAILED: {exc}")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

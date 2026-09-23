"""TEMPORARY probe v2: exact working signatures for PyQt6 6.11 QDBus
callWithCallback + signal connect (both demand QObject + @pyqtSlot)."""

import json
import sys

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusMessage

from cachyuninstall import DBUS_NAME, DBUS_PATH

IFACE = "org.cachyos.Uninstall"
PING = json.dumps({"v": 1, "op": "ping", "payload": {}})


class Bridge(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.results: dict[str, object] = {}

    # -- variant A: slot takes QDBusMessage
    @pyqtSlot(QDBusMessage)
    def reply_msg(self, msg: QDBusMessage) -> None:
        self.results["reply_msg"] = str(msg.arguments()[0]) if msg.arguments() else "<empty>"

    @pyqtSlot(QDBusMessage)
    def error_msg(self, msg: QDBusMessage) -> None:
        self.results["error_msg"] = msg.errorMessage() or "<no-error-str>"

    # -- variant B: slot takes no arguments
    @pyqtSlot()
    def reply_none(self) -> None:
        self.results["reply_none"] = "called"

    @pyqtSlot()
    def error_none(self) -> None:
        self.results["error_none"] = "called"

    # -- progress signal: (str, str, int, int, int, str)
    @pyqtSlot(str, str, int, int, int, str)
    def on_progress(self, kind: str, target: str, cur: int, tot: int, pct: int, msg: str) -> None:
        self.results.setdefault("progress", []).append((kind, target, cur, tot, pct, msg))  # type: ignore[attr-defined]


def main() -> int:
    app = QCoreApplication(sys.argv[:1])
    bus = QDBusConnection.systemBus()
    if not bus.isConnected():
        print("no system bus")
        return 2
    b = Bridge()

    # Variant A: slots taking QDBusMessage
    call = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, IFACE, "Call")
    call.setArguments([PING])
    try:
        ok = bus.callWithCallback(call, b.reply_msg, b.error_msg, 5000)
        print("callWithCallback(QDBusMessage slots): accepted, returned", ok)
    except TypeError as exc:
        print("callWithCallback(QDBusMessage slots): TypeError:", exc)

    # Variant B: no-arg slots
    call2 = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, IFACE, "Call")
    call2.setArguments([PING])
    try:
        ok = bus.callWithCallback(call2, b.reply_none, b.error_none, 5000)
        print("callWithCallback(no-arg slots): accepted, returned", ok)
    except TypeError as exc:
        print("callWithCallback(no-arg slots): TypeError:", exc)

    # Signal connect with typed pyqtSlot
    try:
        bus.connect(DBUS_NAME, DBUS_PATH, IFACE, "Progress", b.on_progress)
        print("connect(Progress, typed pyqtSlot): accepted")
    except TypeError as exc:
        print("connect(Progress, typed pyqtSlot): TypeError:", exc)

    def finish() -> None:
        for k, v in b.results.items():
            print(f"  {k}: {v}")
        print("progress count:", len(b.results.get("progress", [])))  # type: ignore[arg-type]
        app.quit()

    QTimer.singleShot(1500, finish)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

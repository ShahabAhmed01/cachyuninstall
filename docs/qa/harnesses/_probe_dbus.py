"""TEMPORARY probe: can QDBusConnection.callWithCallback deliver replies in
PyQt6 6.11, with (a) a plain closure and (b) a pyqtSlot method? Also check
whether Progress signals arrive while a *blocking* bus.call is in progress
(matters for GUI live-progress + D5 cancel)."""

import json
import sys

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSlot
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage

from cachyuninstall import DBUS_NAME, DBUS_PATH

IFACE = "org.cachyos.Uninstall"
PING = json.dumps({"v": 1, "op": "ping", "payload": {}})


class Probe(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.done_closure = False
        self.done_slot = False
        self.replies: list[str] = []

    @pyqtSlot(QDBusMessage)
    def on_reply(self, msg: QDBusMessage) -> None:
        self.done_slot = True
        self.replies.append(str(msg.arguments()[0]) if msg.arguments() else "<empty>")

    def probe_closure(self, bus: QDBusConnection) -> None:
        call = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, IFACE, "Call")
        call.setArguments([PING])

        def cb(msg: QDBusMessage) -> None:
            self.done_closure = True
            self.replies.append(str(msg.arguments()[0]) if msg.arguments() else "<empty>")

        def eb(msg: QDBusMessage) -> None:
            self.done_closure = f"ERROR: {msg.errorMessage()}"

        try:
            bus.callWithCallback(call, [], cb, eb, 5000)
            print("callWithCallback(closure): accepted (no TypeError)")
        except TypeError as exc:
            print(f"callWithCallback(closure): TypeError: {exc}")

    def probe_slot(self, bus: QDBusConnection) -> None:
        call = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, IFACE, "Call")
        call.setArguments([PING])
        try:
            bus.callWithCallback(call, [], self.on_reply, self.on_reply, 5000)
            print("callWithCallback(pyqtSlot method): accepted")
        except TypeError as exc:
            print(f"callWithCallback(pyqtSlot method): TypeError: {exc}")


def main() -> int:
    app = QCoreApplication(sys.argv[:1])
    bus = QDBusConnection.systemBus()
    if not bus.isConnected():
        print("no system bus")
        return 2
    p = Probe()
    p.probe_closure(bus)
    p.probe_slot(bus)

    # Progress signal observer (does anything arrive during blocking call?)
    got_progress: list[tuple] = []
    bus.connect(
        DBUS_NAME,
        DBUS_PATH,
        IFACE,
        "Progress",
        lambda *args: got_progress.append(tuple(args)),
    )

    def finish() -> None:
        print("closure fired:", p.done_closure)
        print("slot fired:", p.done_slot)
        print("replies:", p.replies)
        print("progress signals observed:", len(got_progress))
        app.quit()

    QTimer.singleShot(1500, finish)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

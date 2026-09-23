"""QtDBus system-service shell around HelperCore.

Verified API facts (probed on PyQt6 6.11):
  * a trailing `QDBusMessage` slot parameter receives the incoming message
    (`message.service()` = caller's unique bus name, for polkit);
  * `QDBus.CallMode.Block`, `QDBusConnection.RegisterOption.ExportAdaptors`;
  * `pyqtClassInfo` sets the exported D-Bus interface name.

A removal runs on a worker QThread while the Call() method parks on a nested
QEventLoop, so Progress signals are delivered live and Cancel stays
processable during the transaction (best-effort interrupt, D5).
"""

from __future__ import annotations

import json
import logging
import sys

from PyQt6.QtCore import QEventLoop, QObject, QThread, pyqtClassInfo, pyqtSignal, pyqtSlot
from PyQt6.QtDBus import QDBusAbstractAdaptor, QDBusConnection, QDBusMessage

from cachyuninstall import DBUS_NAME, DBUS_PATH
from cachyuninstall.privilege.backend import AlpmBackend, TxEvent
from cachyuninstall.privilege.helper import HelperCore, PolkitAuthorizer

LOG = logging.getLogger("cachyuninstall.helper.service")


class _SignalSink(QObject):
    """Backend events → D-Bus progress signal."""

    progressed = pyqtSignal(str, str, int, int, int, str)

    def emit(self, event: TxEvent) -> None:
        # Defensive coercion: pyalpm callbacks may hand us non-str/int values;
        # a signal type error here would crash the worker and lose the reply.
        self.progressed.emit(
            str(event.kind),
            str(event.target),
            int(event.current),
            int(event.total),
            int(event.percent),
            str(event.message),
        )


class _RemovalWorker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, core: HelperCore, request_json: str, bus_name: str) -> None:
        super().__init__()
        self._core = core
        self._request_json = request_json
        self._bus_name = bus_name

    @pyqtSlot()
    def run(self) -> None:
        try:
            reply = self._core.handle(self._request_json, self._bus_name)
        except Exception:  # pragma: no cover - defensive; core catches all
            LOG.exception("worker crashed")
            reply = '{"v":1,"ok":false,"code":"internal-error","message":"Worker failure.","removed":[]}'
        self.finished.emit(reply)

    # NOTE: even if a Progress emit raises inside the worker's call stack,
    # HelperCore.handle() catches Exception and returns an error reply, so
    # finished is always emitted and the caller never hangs.


@pyqtClassInfo("D-Bus Interface", "org.cachyos.Uninstall")
class UninstallAdaptor(QDBusAbstractAdaptor):
    """D-Bus front-end; all policy decisions live in HelperCore."""

    progressed = pyqtSignal(str, str, int, int, int, str)

    def __init__(self, parent: QObject, core: HelperCore, sink: _SignalSink) -> None:
        super().__init__(parent)
        self._core = core
        self._sink = sink
        self._sink.progressed.connect(self.progressed)

    @pyqtSlot(str, QDBusMessage, result=str)
    def Call(self, message_json: str, dbus_message: QDBusMessage) -> str:
        caller = dbus_message.service()
        op = ""
        try:
            parsed = json.loads(message_json)
            op = parsed.get("op", "") if isinstance(parsed, dict) else ""
        except (json.JSONDecodeError, AttributeError):
            pass
        if op == "remove_packages":
            return self._run_removal(message_json, caller)
        return self._core.handle(message_json, caller)

    def _run_removal(self, message_json: str, caller: str) -> str:
        # Fast-fail validation must not block; spin the loop during execution.
        thread = QThread(self)
        worker = _RemovalWorker(self._core, message_json, caller)
        worker.moveToThread(thread)
        result = {"reply": ""}
        loop = QEventLoop(self)

        def _done(reply: str) -> None:
            result["reply"] = reply
            loop.quit()

        worker.finished.connect(_done)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.start()
        loop.exec()  # progress signals + Cancel processed while waiting
        thread.wait(30000)
        worker.deleteLater()
        thread.deleteLater()
        return result["reply"]


def main() -> int:
    from PyQt6.QtCore import QCoreApplication

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QCoreApplication(sys.argv)
    app.setApplicationName("cachyuninstall-helper")

    sink = _SignalSink()
    core = HelperCore(backend=AlpmBackend(), authorizer=PolkitAuthorizer())
    core.sink = sink

    host = QObject()
    UninstallAdaptor(host, core, sink)

    bus = QDBusConnection.systemBus()
    if not bus.isConnected():
        LOG.error("Cannot connect to the system bus")
        return 2
    if not bus.registerObject(DBUS_PATH, host, QDBusConnection.RegisterOption.ExportAdaptors):
        LOG.error("Cannot register helper object (permissions?)")
        return 3
    if not bus.registerService(DBUS_NAME):
        LOG.error("Cannot own %s (already running?)", DBUS_NAME)
        return 4
    LOG.info("helper ready on %s", DBUS_NAME)
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

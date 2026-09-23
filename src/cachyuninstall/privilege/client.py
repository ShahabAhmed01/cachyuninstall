"""Client for the privileged helper (GUI and CLI).

Builds the protocol message from an approved RemovalPlan and issues the D-Bus
call. Progress arrives via the helper's ``progressed`` D-Bus signal.

Probe-verified on PyQt6 6.11: ``QDBusConnection.connect`` and
``callWithCallback`` accept ONLY ``@pyqtSlot``-decorated methods of a
``QObject`` — plain lambdas/closures raise TypeError at runtime. All Qt
endpoints therefore live on the internal ``_Bridge`` object; handlers are
plain Python callables stored on it and invoked from the slot bodies on the
calling (GUI) thread.

Two call modes:
  * async (default, GUI): callWithCallback — the GUI event loop keeps
    running, so Progress signals repaint the dialog and Cancel stays live;
  * blocking (CLI): QDBus.CallMode.Block — the CLI has no event loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSlot
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusError, QDBusMessage

from cachyuninstall import DBUS_NAME, DBUS_PATH
from cachyuninstall.core.models import RemovalPlan
from cachyuninstall.privilege.backend import TxEvent
from cachyuninstall.privilege.protocol import (
    HelperReply,
    decode_reply,
    encode_request,
)

LOG = logging.getLogger("cachyuninstall.client")

_IFACE = "org.cachyos.Uninstall"

_PROGRESS_TYPES = (str, str, int, int, int, str)


class _Bridge(QObject):
    """Qt endpoints (typed pyqtSlot methods) forwarding to plain handlers."""

    def __init__(self) -> None:
        super().__init__()
        self.progress_handler: Callable[[TxEvent], None] | None = None
        self.reply_handler: Callable[[HelperReply], None] | None = None

    @pyqtSlot(*_PROGRESS_TYPES)
    def on_progress(  # noqa: PLR0917 - arity is fixed by the D-Bus signal signature
        self,
        kind: str,
        target: str,
        current: int,
        total: int,
        percent: int,
        message: str,
    ) -> None:
        if self.progress_handler is not None:
            self.progress_handler(
                TxEvent(
                    kind=kind,
                    target=target,
                    current=current,
                    total=total,
                    percent=percent,
                    message=message,
                )
            )

    @pyqtSlot(QDBusMessage)
    def on_reply(self, message: QDBusMessage) -> None:
        handler, self.reply_handler = self.reply_handler, None
        if handler is not None:
            handler(_decode_message(message))

    @pyqtSlot(QDBusError, QDBusMessage)
    def on_error(self, error: QDBusError, _message: QDBusMessage) -> None:
        handler, self.reply_handler = self.reply_handler, None
        if handler is not None:
            handler(HelperReply(ok=False, code="dbus-error", message=error.message() or "D-Bus call failed."))


def _decode_message(message: QDBusMessage) -> HelperReply:
    if message.errorMessage():
        return HelperReply(ok=False, code="dbus-error", message=message.errorMessage())
    args = message.arguments()
    if not args:
        return HelperReply(ok=False, code="empty-reply", message="Helper returned nothing.")
    from cachyuninstall.core.errors import ProtocolError

    try:
        return decode_reply(str(args[0]))
    except ProtocolError as exc:
        return HelperReply(ok=False, code="protocol-error", message=str(exc))


class HelperClient:
    def __init__(self, connection: QDBusConnection | None = None) -> None:
        self._bus = connection or QDBusConnection.systemBus()
        self._bridge: _Bridge | None = None
        self._progress_connected = False

    def _ensure_bridge(self) -> _Bridge:
        if self._bridge is None:
            self._bridge = _Bridge()
        return self._bridge

    # ------------------------------------------------------------- plumbing
    def is_available(self) -> bool:
        """True when the helper answers a protocol ping on the system bus."""
        call = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, _IFACE, "Call")
        call.setArguments([encode_request("ping", {})])

        reply = self._bus.call(call, QDBus.CallMode.Block, 1500)
        if reply.errorMessage():
            return False
        args = reply.arguments()
        if not args:
            return False
        try:
            return decode_reply(str(args[0])).ok
        except Exception:
            return False

    def connect_progress(self, handler: Callable[[TxEvent], None]) -> None:
        """Route the helper's progress signal into `handler`.

        The D-Bus member name is ``progressed`` — the Qt signal declared on
        ``UninstallAdaptor`` is exported verbatim (verified via busctl
        introspect: ``.progressed signal ssiiis``). Subscribing to a
        differently-cased name matches nothing (match rules are not
        validated) and silently delivers zero events.

        The Qt connection is established exactly once; later calls just
        replace the handler (the previous progress dialog is gone by then).
        """
        bridge = self._ensure_bridge()
        bridge.progress_handler = handler
        if not self._progress_connected:
            ok = self._bus.connect(
                DBUS_NAME,
                DBUS_PATH,
                _IFACE,
                "progressed",
                bridge.on_progress,
            )
            if not ok:
                LOG.warning("could not subscribe to progress signal")
            self._progress_connected = True

    # ------------------------------------------------------------ operations
    def remove_packages(
        self,
        plan: RemovalPlan,
        on_finished: Callable[[HelperReply], None],
        *,
        blocking: bool = False,
    ) -> HelperReply | None:
        """Send the approved plan to the helper.

        blocking=False (GUI): returns immediately; `on_finished` runs later on
        the GUI thread when the reply arrives (event loop must be running).
        blocking=True (CLI): performs the call synchronously, invokes
        `on_finished`, and returns the reply.
        """
        payload = {
            "plan_id": plan.plan_id,
            "targets": [str(t) for t in plan.targets],
            "cascade": [str(c) for c in plan.cascade],
            "generation": plan.system_generation,
            "digest": plan.digest(),
        }
        message_json = encode_request("remove_packages", payload)
        call = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, _IFACE, "Call")
        call.setArguments([message_json])

        if blocking:
            reply = _decode_message(self._bus.call(call, QDBus.CallMode.Block, 300000))
            on_finished(reply)
            return reply

        bridge = self._ensure_bridge()
        bridge.reply_handler = on_finished
        started = self._bus.callWithCallback(call, bridge.on_reply, bridge.on_error, 300000)
        if not started:
            bridge.reply_handler = None
            on_finished(HelperReply(ok=False, code="dbus-error", message="Could not send the request."))
        return None

    def cancel_current(self) -> None:
        message = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH, _IFACE, "Call")
        message.setArguments([encode_request("cancel", {})])
        self._bus.asyncCall(message)

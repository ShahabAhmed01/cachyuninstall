"""Privileged helper: a minimal D-Bus system service for ALPM removal.

Design (D2): the ONLY verb is RemovePackages (+ Ping/Cancel). There is no
file deletion and no command execution — root side speaks libalpm only.

Structure:
  * HelperCore — transport-free: authorization → protocol validation →
    staleness re-check → digest verification → backend execution.
    Fully unit-testable with a fake backend + fake authorizer.
  * PolkitAuthorizer — polkit CheckAuthorization (dbus-python reads polkit's
    struct reply natively; PyQt6's QDBusArgument has no struct extraction).
  * HelperService — QtDBus adaptor exposing HelperCore on the system bus.
"""

from __future__ import annotations

import logging
from typing import Protocol

from cachyuninstall import POLKIT_ACTION_REMOVE
from cachyuninstall.core.errors import (
    AuthorizationDenied,
    CuError,
    ProtocolError,
    StalePlan,
)
from cachyuninstall.core.models import PackageName
from cachyuninstall.privilege.backend import EventSink, TransactionBackend, TxEvent
from cachyuninstall.privilege.protocol import (
    HelperReply,
    RemoveRequest,
    decode_request,
    encode_reply,
)

LOG = logging.getLogger("cachyuninstall.helper")


class Authorizer(Protocol):
    def check(self, caller_bus_name: str, action_id: str) -> bool: ...


class _NullSink:
    def emit(self, event: TxEvent) -> None:  # pragma: no cover - trivial
        LOG.debug("event: %s %s", event.kind, event.message)


class HelperCore:
    """Authorization + validation + execution. No D-Bus/Qt imports here."""

    def __init__(self, backend: TransactionBackend, authorizer: Authorizer) -> None:
        self._backend = backend
        self._authorizer = authorizer
        self.sink: EventSink = _NullSink()  # swapped for a D-Bus emitter by the service

    def handle(self, raw_message: str, caller_bus_name: str) -> str:
        """Entrypoint for one client message; always returns a reply JSON."""
        try:
            op, request = decode_request(raw_message)
            reply = self._dispatch(op, request, caller_bus_name)
        # A crash mid-transaction must still yield a reply (never hang the
        # caller), so every exception path is funnelled into encode_reply.
        except AuthorizationDenied as exc:
            reply = HelperReply(ok=False, code="authorization-denied", message=str(exc))
        except StalePlan as exc:
            reply = HelperReply(ok=False, code="stale-plan", message=str(exc))
        except ProtocolError as exc:
            reply = HelperReply(ok=False, code="protocol-error", message=str(exc))
        except CuError as exc:
            reply = HelperReply(ok=False, code=type(exc).__name__, message=str(exc))
        except Exception:
            LOG.exception("helper failure")
            reply = HelperReply(ok=False, code="internal-error", message="Internal helper error.")
        return encode_reply(reply)

    def _dispatch(self, op: str, request: RemoveRequest | None, caller_bus_name: str) -> HelperReply:
        if op == "ping":
            return HelperReply(ok=True, message="cachyuninstall-helper alive")
        if op == "cancel":
            self._backend.request_interrupt()
            return HelperReply(ok=True, code="cancel-requested")
        return self._remove(self._require(request), caller_bus_name)

    @staticmethod
    def _require(request: RemoveRequest | None) -> RemoveRequest:
        if request is None:
            raise ProtocolError("Missing plan payload")
        return request

    def _remove(self, request: RemoveRequest, caller: str) -> HelperReply:
        if not self._authorizer.check(caller, POLKIT_ACTION_REMOVE):
            raise AuthorizationDenied("Authorization was denied or cancelled.")

        # Staleness gate (D3): revalidate against the live database.
        current_generation = self._backend.generation()
        if current_generation != request.generation:
            raise StalePlan(
                "The package database changed since the plan was approved. Re-open the preview and try again."
            )
        if _plan_digest(request.targets, request.cascade, current_generation) != request.digest:
            raise StalePlan("The approved plan does not match live system state.")

        all_names = (*request.targets, *request.cascade)
        for name in all_names:
            if not self._backend.is_installed(name):
                raise StalePlan(f"Package '{name}' is no longer installed.")

        removed = self._backend.remove(all_names, self.sink)
        return HelperReply(ok=True, message="Packages removed.", removed=tuple(removed))


def _plan_digest(targets: tuple[PackageName, ...], cascade: tuple[PackageName, ...], generation: int) -> str:
    """Must match core.models.RemovalPlan.digest() bit-for-bit."""
    import hashlib

    h = hashlib.sha256()
    h.update(b"pacman")
    for name in (*targets, *cascade):
        h.update(str(name).lower().encode())
        h.update(b"\0")
    h.update(str(generation).encode())
    return h.hexdigest()


class PolkitAuthorizer:
    """polkit CheckAuthorization over the system bus (dbus-python)."""

    POLKIT_IFACE = "org.freedesktop.PolicyKit1.Authority"
    POLKIT_NAME = "org.freedesktop.PolicyKit1"
    POLKIT_PATH = "/org/freedesktop/PolicyKit1/Authority"

    def check(self, caller_bus_name: str, action_id: str) -> bool:
        try:
            import dbus
        except ImportError:
            LOG.error("python-dbus unavailable; denying by default")
            return False
        try:
            authority = dbus.SystemBus().get_object(self.POLKIT_NAME, self.POLKIT_PATH)
            iface = dbus.Interface(authority, self.POLKIT_IFACE)
            subject = ("system-bus-name", {"name": caller_bus_name})
            authorized, _is_challenge, _details = iface.CheckAuthorization(
                subject,
                action_id,
                {},
                dbus.UInt32(1),
                "",  # 1 = AllowUserInteraction
            )
            LOG.info("polkit %s for %s: %s", action_id, caller_bus_name, bool(authorized))
            return bool(authorized)
        except Exception:
            LOG.exception("polkit check failed; denying")
            return False

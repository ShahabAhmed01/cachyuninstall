"""HelperCore security tests: auth denial, staleness, digest, attack shapes."""

from __future__ import annotations

import json

from cachyuninstall.core.models import PackageName
from cachyuninstall.privilege.backend import EventSink, TxEvent
from cachyuninstall.privilege.helper import HelperCore, _plan_digest
from cachyuninstall.privilege.protocol import decode_reply, encode_request


class FakeBackend:
    def __init__(self, installed: set[str], generation: int = 42) -> None:
        self.installed = set(installed)
        self._generation = generation
        self.removed: list[str] = []
        self.interrupted = False

    def generation(self) -> int:
        return self._generation

    def is_installed(self, name: PackageName) -> bool:
        return str(name) in self.installed

    def remove(self, names: tuple[PackageName, ...], sink: EventSink) -> list[PackageName]:
        sink.emit(TxEvent(kind="stage", message="test"))
        for name in names:
            self.installed.discard(str(name))
            self.removed.append(str(name))
        return list(names)

    def request_interrupt(self) -> None:
        self.interrupted = True


class AllowAll:
    def check(self, caller_bus_name: str, action_id: str) -> bool:
        return True


class DenyAll:
    def check(self, caller_bus_name: str, action_id: str) -> bool:
        return False


def _msg(targets: list[str], generation: int, cascade: list[str] | None = None) -> str:
    cascade = cascade or []
    names = tuple(PackageName(t) for t in targets)
    casc = tuple(PackageName(c) for c in cascade)
    return encode_request(
        "remove_packages",
        {
            "plan_id": "plan-1",
            "targets": list(targets),
            "cascade": list(cascade),
            "generation": generation,
            "digest": _plan_digest(names, casc, generation),
        },
    )


def test_successful_removal() -> None:
    core = HelperCore(FakeBackend({"firefox", "dep"}), AllowAll())
    reply = decode_reply(core.handle(_msg(["firefox"], 42), ":1.9"))
    assert reply.ok
    assert "firefox" in map(str, reply.removed)


def test_authorization_denied_executes_nothing() -> None:
    backend = FakeBackend({"firefox"})
    core = HelperCore(backend, DenyAll())
    reply = decode_reply(core.handle(_msg(["firefox"], 42), ":1.9"))
    assert not reply.ok
    assert reply.code == "authorization-denied"
    assert backend.removed == []


def test_stale_generation_rejected() -> None:
    backend = FakeBackend({"firefox"}, generation=99)
    core = HelperCore(backend, AllowAll())
    reply = decode_reply(core.handle(_msg(["firefox"], 42), ":1.9"))
    assert not reply.ok
    assert reply.code == "stale-plan"
    assert backend.removed == []


def test_digest_mismatch_rejected() -> None:
    msg_json = json.loads(_msg(["firefox"], 42))
    msg_json["payload"]["targets"] = ["evil-extra"]  # modify without digest update
    # digest no longer covers "evil-extra"
    core = HelperCore(FakeBackend({"firefox", "evil-extra"}), AllowAll())
    reply = decode_reply(core.handle(json.dumps(msg_json), ":1.9"))
    assert not reply.ok
    assert reply.code == "stale-plan"


def test_vanished_package_between_plan_and_exec() -> None:
    core = HelperCore(FakeBackend(set()), AllowAll())
    reply = decode_reply(core.handle(_msg(["firefox"], 42), ":1.9"))
    assert not reply.ok
    assert reply.code == "stale-plan"


def test_malformed_message_rejected_without_side_effects() -> None:
    backend = FakeBackend({"firefox"})
    core = HelperCore(backend, AllowAll())
    for raw in ("not json", "{}", '{"v": 1, "op": "execute", "payload": {}}', "[]"):
        reply = decode_reply(core.handle(raw, ":1.9"))
        assert not reply.ok
    assert backend.removed == []


def test_ping_and_cancel() -> None:
    backend = FakeBackend(set())
    core = HelperCore(backend, DenyAll())  # ping/cancel need no authorization
    ok = decode_reply(core.handle(encode_request("ping", {}), ":1.9"))
    assert ok.ok
    cancel = decode_reply(core.handle(encode_request("cancel", {}), ":1.9"))
    assert cancel.ok and backend.interrupted


def test_internal_error_never_leaks_traceback() -> None:
    class Boom(FakeBackend):
        def remove(self, names: tuple[PackageName, ...], sink: EventSink) -> list[PackageName]:
            raise RuntimeError("explosive internals " + "/root/secret/path")

    core = HelperCore(Boom({"firefox"}), AllowAll())
    reply = decode_reply(core.handle(_msg(["firefox"], 42), ":1.9"))
    assert not reply.ok
    assert reply.code == "internal-error"
    assert "secret" not in reply.message and "explosive" not in reply.message

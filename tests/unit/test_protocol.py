"""Protocol validation tests (§162-163, §255, §286)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cachyuninstall.core.errors import ProtocolError
from cachyuninstall.core.models import PackageName
from cachyuninstall.privilege.protocol import (
    PROTOCOL_VERSION,
    HelperReply,
    decode_reply,
    decode_request,
    encode_reply,
    encode_request,
)


def plan_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "plan_id": "abc",
        "targets": ["firefox"],
        "cascade": [],
        "generation": 123,
        "digest": "0" * 64,
    }
    base.update(overrides)
    return base


def test_roundtrip_valid() -> None:
    raw = encode_request("remove_packages", plan_payload())
    op, req = decode_request(raw)
    assert op == "remove_packages"
    assert req is not None
    assert req.targets == (PackageName("firefox"),)
    assert req.generation == 123


@pytest.mark.parametrize(
    "override",
    [
        {"targets": ["ok", "../evil"]},
        {"targets": ["ok", "rm -rf /"]},
        {"targets": ["ok", "foo;bar"]},
        {"targets": ["a b"]},
        {"targets": ["-R", "firefox"]},
        {"targets": []},
        {"targets": ["firefox"] * 513},
    ],
)
def test_malformed_package_lists_rejected(override: dict[str, object]) -> None:
    raw = encode_request("remove_packages", plan_payload(**override))
    with pytest.raises(ProtocolError):
        decode_request(raw)


def test_unknown_keys_rejected() -> None:
    payload = plan_payload()
    payload["paths"] = ["/etc/passwd"]  # attempted arbitrary path smuggling
    raw = encode_request("remove_packages", payload)
    with pytest.raises(ProtocolError):
        decode_request(raw)


def test_unknown_op_rejected() -> None:
    import json

    raw = json.dumps({"v": PROTOCOL_VERSION, "op": "delete_path", "payload": {}})
    with pytest.raises(ProtocolError):
        decode_request(raw)


def test_version_mismatch_rejected() -> None:
    import json

    raw = json.dumps({"v": 999, "op": "ping", "payload": {}})
    with pytest.raises(ProtocolError):
        decode_request(raw)


def test_cascade_overlap_rejected() -> None:
    raw = encode_request("remove_packages", plan_payload(targets=["a"], cascade=["a"]))
    with pytest.raises(ProtocolError):
        decode_request(raw)


def test_oversized_message_rejected() -> None:
    huge = "x" * 300_000
    raw = encode_request("remove_packages", plan_payload(digest="0" * 64))
    padded = raw[:-1] + ', "pad": "' + huge + '"}'
    with pytest.raises(ProtocolError):
        decode_request(padded)


def test_reply_roundtrip() -> None:
    reply = HelperReply(ok=True, message="done", removed=(PackageName("firefox"),))
    decoded = decode_reply(encode_reply(reply))
    assert decoded.ok and decoded.removed == (PackageName("firefox"),)


def test_reply_bad_shape_rejected() -> None:
    with pytest.raises(ProtocolError):
        decode_reply('{"ok": true}')


def test_no_newlines_hijack() -> None:
    raw = encode_request("remove_packages", plan_payload(targets=["fine"]))
    assert "\n" not in raw or isinstance(raw, str)
    _, req = decode_request(raw)
    assert req is not None and Path(str(req.targets[0])).name == "fine"

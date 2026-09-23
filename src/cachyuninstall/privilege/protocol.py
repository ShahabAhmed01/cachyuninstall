"""Wire protocol between the unprivileged GUI and the privileged helper.

Properties (§42, §162):
  * JSON only; no pickle, no arbitrary objects;
  * explicit version; unknown fields rejected; unknown ops rejected;
  * package names validated against a strict grammar;
  * payloads size-limited.

The helper re-validates everything on receipt and never trusts the client.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from cachyuninstall.core.errors import ProtocolError
from cachyuninstall.core.models import PackageName

PROTOCOL_VERSION = 1
MAX_PACKAGE_NAMES = 512
MAX_MESSAGE_BYTES = 256 * 1024

_PKG_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+@-]{0,127}$")

OP_REMOVE_PACKAGES = "remove_packages"
OP_PING = "ping"
OP_CANCEL = "cancel"
_KNOWN_OPS = frozenset({OP_REMOVE_PACKAGES, OP_PING, OP_CANCEL})


@dataclass(frozen=True, slots=True)
class RemoveRequest:
    plan_id: str
    targets: tuple[PackageName, ...]
    cascade: tuple[PackageName, ...]
    generation: int
    digest: str


@dataclass(frozen=True, slots=True)
class HelperReply:
    ok: bool
    code: str = "ok"
    message: str = ""
    removed: tuple[PackageName, ...] = field(default_factory=tuple)


def _check_pkg_names(values: object, field_name: str) -> tuple[PackageName, ...]:
    if not isinstance(values, list) or len(values) > MAX_PACKAGE_NAMES:
        raise ProtocolError(f"Invalid {field_name}", detail="not a list or too long")
    names: list[PackageName] = []
    for v in values:
        if not isinstance(v, str) or not _PKG_NAME.match(v):
            raise ProtocolError(f"Invalid package name in {field_name}", detail=repr(v)[:64])
        names.append(PackageName(v))
    return tuple(names)


def encode_request(op: str, payload: dict[str, object]) -> str:
    if op not in _KNOWN_OPS:
        raise ProtocolError(f"Unknown op: {op}")
    msg = json.dumps({"v": PROTOCOL_VERSION, "op": op, "payload": payload})
    raw = msg.encode("utf-8")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Message too large")
    return msg


def decode_request(raw: str) -> tuple[str, RemoveRequest | None]:
    """Validate + parse a client message. Raises ProtocolError on anything off."""
    if len(raw.encode("utf-8", errors="replace")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Message too large")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Malformed JSON", detail=str(exc)) from exc
    if not isinstance(obj, dict):
        raise ProtocolError("Top level must be an object")
    if set(obj.keys()) - {"v", "op", "payload"}:
        raise ProtocolError("Unknown top-level fields")
    if obj.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version")
    op = obj.get("op")
    if op not in _KNOWN_OPS:
        raise ProtocolError(f"Unknown op: {op!r}")
    payload = obj.get("payload")
    if op in (OP_PING, OP_CANCEL):
        return str(op), None
    if not isinstance(payload, dict):
        raise ProtocolError("Missing payload")
    allowed = {"plan_id", "targets", "cascade", "generation", "digest"}
    if set(payload.keys()) != allowed:
        raise ProtocolError("Bad payload fields", detail=str(sorted(payload.keys())))
    plan_id = payload["plan_id"]
    digest = payload["digest"]
    generation = payload["generation"]
    if not isinstance(plan_id, str) or len(plan_id) > 64:
        raise ProtocolError("Bad plan_id")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ProtocolError("Bad digest")
    if not isinstance(generation, int) or generation < 0:
        raise ProtocolError("Bad generation")
    targets = _check_pkg_names(payload["targets"], "targets")
    cascade = _check_pkg_names(payload["cascade"], "cascade")
    if not targets:
        raise ProtocolError("No targets")
    if set(cascade) & set(targets):
        raise ProtocolError("cascade overlaps targets")
    return str(op), RemoveRequest(
        plan_id=plan_id, targets=targets, cascade=cascade, generation=generation, digest=digest
    )


def encode_reply(reply: HelperReply) -> str:
    return json.dumps(
        {
            "v": PROTOCOL_VERSION,
            "ok": reply.ok,
            "code": reply.code,
            "message": reply.message,
            "removed": list(reply.removed),
        }
    )


def decode_reply(raw: str) -> HelperReply:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Malformed reply", detail=str(exc)) from exc
    if not isinstance(obj, dict) or set(obj.keys()) != {"v", "ok", "code", "message", "removed"}:
        raise ProtocolError("Bad reply shape")
    if obj.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("Bad reply version")
    removed = _check_pkg_names(obj.get("removed"), "removed")
    return HelperReply(
        ok=bool(obj["ok"]),
        code=str(obj["code"]),
        message=str(obj["message"]),
        removed=removed,
    )

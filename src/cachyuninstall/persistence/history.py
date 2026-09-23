"""History + crash journal at ~/.local/share/cachyuninstall/history.db.

SQLite (D13): atomic, crash-safe journalling. The journal records *intent
before execution*; on next launch, unfinished records are re-derived against
the live system — a journal entry is NEVER treated as proof of system state
(§187).

No secrets, no file contents — paths of removed items only.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

DATA_DIR = Path("~/.local/share/cachyuninstall").expanduser()
_DB_PATH = DATA_DIR / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    action TEXT NOT NULL,
    subject TEXT NOT NULL,
    provider TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL UNIQUE,
    ts INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL
);
"""

RETENTION_S = 365 * 24 * 3600  # history kept one year, then pruned on read


class HistoryKind(Enum):
    UNINSTALL = "uninstall"
    CLEANUP = "cleanup"
    QUARANTINE = "quarantine"
    RESTORE = "restore"


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    ts: int
    action: str
    subject: str
    provider: str
    detail: dict[str, object]
    result: str


@dataclass(frozen=True, slots=True)
class JournalRecord:
    plan_id: str
    ts: int
    payload: dict[str, object]
    state: str  # "started" | "done" | "failed"


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ---------------------------------------------------------------- history
    def record(
        self, kind: HistoryKind, subject: str, provider: str, detail: dict[str, object], result: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO history (ts, action, subject, provider, detail_json, result)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (int(time.time()), kind.value, subject, provider, json.dumps(detail), result),
            )
            conn.execute("DELETE FROM history WHERE ts < ?", (int(time.time()) - RETENTION_S,))

    def entries(self, limit: int = 500) -> list[HistoryEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts, action, subject, provider, detail_json, result FROM history"
                " ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            HistoryEntry(
                ts=int(ts),
                action=action,
                subject=subject,
                provider=provider,
                detail=json.loads(detail),
                result=result,
            )
            for ts, action, subject, provider, detail, result in rows
        ]

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM history")

    # ---------------------------------------------------------------- journal
    def journal_start(self, plan_id: str, payload: dict[str, object]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO journal (plan_id, ts, payload_json, state)"
                " VALUES (?, ?, ?, 'started')",
                (plan_id, int(time.time()), json.dumps(payload)),
            )

    def journal_finish(self, plan_id: str, state: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE journal SET state = ? WHERE plan_id = ?", (state, plan_id))

    def unfinished(self) -> list[JournalRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT plan_id, ts, payload_json, state FROM journal WHERE state = 'started'"
            ).fetchall()
        return [
            JournalRecord(plan_id=pid, ts=int(ts), payload=json.loads(payload), state=state)
            for pid, ts, payload, state in rows
        ]

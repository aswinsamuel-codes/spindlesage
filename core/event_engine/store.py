"""SQLite persistence for recommendations, approvals and the audit trail.

SQLite keeps the development setup dependency-free and laptop-friendly. The
schema uses plain SQL types so it can move to PostgreSQL later.

The audit trail is append-only and hash-chained: each record stores the hash
of the previous record, and its own hash covers its content plus that link.
Editing or deleting any past record breaks every hash after it, which
verify_audit_chain() reports.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

GENESIS_HASH = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    engine TEXT NOT NULL,
    mode TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rec_machine ON recommendations (machine_id, created_utc);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL REFERENCES recommendations (id),
    machine_id TEXT NOT NULL,
    action_index INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    urgency TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence_ids TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    expires_utc TEXT NOT NULL,
    decided_by TEXT,
    decided_utc TEXT,
    decision_note TEXT,
    completed_by TEXT,
    completed_utc TEXT,
    completion_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_approval_status ON approvals (status, created_utc);

CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    details TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""

_AUDIT_FIELDS = (
    "event_id",
    "ts_utc",
    "actor",
    "actor_role",
    "action",
    "subject_type",
    "subject_id",
    "details",
)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def audit_hash(prev_hash: str, record: dict) -> str:
    body = {k: record[k] for k in _AUDIT_FIELDS}
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    records: int
    first_broken_seq: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "records": self.records,
            "first_broken_seq": self.first_broken_seq,
            "reason": self.reason,
        }


class OperationsStore:
    def __init__(self, path: Path | str = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    # -- audit -------------------------------------------------------------

    def append_audit(
        self,
        conn: sqlite3.Connection,
        *,
        ts_utc: str,
        actor: str,
        actor_role: str,
        action: str,
        subject_type: str,
        subject_id: str,
        details: dict,
    ) -> dict:
        """Append one audit record. Call inside transaction() with the change it records."""
        row = conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = row["hash"] if row else GENESIS_HASH
        record = {
            "event_id": str(uuid.uuid4()),
            "ts_utc": ts_utc,
            "actor": actor,
            "actor_role": actor_role,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "details": _canonical(details),
        }
        record["prev_hash"] = prev_hash
        record["hash"] = audit_hash(prev_hash, record)
        conn.execute(
            "INSERT INTO audit_events (event_id, ts_utc, actor, actor_role, action, subject_type,"
            " subject_id, details, prev_hash, hash) VALUES (:event_id, :ts_utc, :actor,"
            " :actor_role, :action, :subject_type, :subject_id, :details, :prev_hash, :hash)",
            record,
        )
        return record

    def audit_events(
        self, subject_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        query = "SELECT * FROM audit_events"
        params: list = []
        if subject_id:
            query += " WHERE subject_id = ?"
            params.append(subject_id)
        query += " ORDER BY seq LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [{**dict(r), "details": json.loads(r["details"])} for r in rows]

    def verify_audit_chain(self) -> ChainVerification:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
        prev_hash = GENESIS_HASH
        for row in rows:
            record = dict(row)
            if record["prev_hash"] != prev_hash:
                return ChainVerification(False, len(rows), record["seq"], "broken link")
            if audit_hash(prev_hash, record) != record["hash"]:
                return ChainVerification(False, len(rows), record["seq"], "content modified")
            prev_hash = record["hash"]
        return ChainVerification(True, len(rows))

    # -- recommendations and approvals ----------------------------------------

    def insert_recommendation(self, conn: sqlite3.Connection, row: dict) -> None:
        conn.execute(
            "INSERT INTO recommendations (id, machine_id, created_utc, requested_by, engine, mode,"
            " risk_level, approval_status, payload) VALUES (:id, :machine_id, :created_utc,"
            " :requested_by, :engine, :mode, :risk_level, :approval_status, :payload)",
            row,
        )

    def insert_approval(self, conn: sqlite3.Connection, row: dict) -> None:
        conn.execute(
            "INSERT INTO approvals (id, recommendation_id, machine_id, action_index, action_type,"
            " urgency, description, evidence_ids, status, requested_by, created_utc, expires_utc)"
            " VALUES (:id, :recommendation_id, :machine_id, :action_index, :action_type, :urgency,"
            " :description, :evidence_ids, :status, :requested_by, :created_utc, :expires_utc)",
            row,
        )

    _UPDATABLE_APPROVAL_COLUMNS = frozenset(
        {
            "status",
            "decided_by",
            "decided_utc",
            "decision_note",
            "completed_by",
            "completed_utc",
            "completion_note",
        }
    )

    def update_approval(self, conn: sqlite3.Connection, approval_id: str, **fields) -> None:
        unknown = set(fields) - self._UPDATABLE_APPROVAL_COLUMNS
        if not fields or unknown:
            raise ValueError(f"Cannot update approval columns: {sorted(unknown) or 'none given'}")
        # Column names come only from the allow-list above; all values are bound parameters.
        assignments = ", ".join(f"{name} = :{name}" for name in sorted(fields))
        conn.execute(
            f"UPDATE approvals SET {assignments} WHERE id = :id",  # nosec B608
            {**fields, "id": approval_id},
        )

    def get_recommendation(self, recommendation_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recommendations WHERE id = ?", (recommendation_id,)
            ).fetchone()
        return _recommendation(row) if row else None

    def list_recommendations(self, machine_id: str | None = None, limit: int = 50) -> list[dict]:
        query = "SELECT * FROM recommendations"
        params: list = []
        if machine_id:
            query += " WHERE machine_id = ?"
            params.append(machine_id)
        query += " ORDER BY created_utc DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_recommendation(r) for r in rows]

    def get_approval(self, approval_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
        with self._lock:
            row = (
                (conn or self._conn)
                .execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
                .fetchone()
            )
        return _approval(row) if row else None

    def list_approvals(
        self,
        status: str | None = None,
        recommendation_id: str | None = None,
        machine_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses, params = [], []
        for column, value in (
            ("status", status),
            ("recommendation_id", recommendation_id),
            ("machine_id", machine_id),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        query = "SELECT * FROM approvals"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_utc, action_index LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_approval(r) for r in rows]


def _recommendation(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["payload"] = json.loads(data["payload"])
    return data


def _approval(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["evidence_ids"] = json.loads(data["evidence_ids"])
    return data

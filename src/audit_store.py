"""Private SQLite case decisions and name reviews with an append-only hash chain.

The chain detects edits against a previously exported head. It is not a digital
signature or protection against an administrator rewriting the entire database.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from src.common import digest

GENESIS = "0" * 64


class AuditStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, entity_id TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL, previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS event_entity ON events(kind,entity_id,sequence)")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, request_id, kind, entity_id, payload):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT sequence,kind,entity_id,payload,event_hash FROM events WHERE request_id=?",
                                  (request_id,)).fetchone()
            if existing:
                if tuple(existing[1:4]) != (kind, entity_id, encoded):
                    raise ValueError("Request ID already used for a different event")
                return {"sequence": existing[0], "event_hash": existing[4], "duplicate": True}
            previous = db.execute("SELECT event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
            previous = previous[0] if previous else GENESIS
            created = datetime.now(timezone.utc).isoformat()
            event_hash = digest([request_id, kind, entity_id, payload, created, previous])
            cursor = db.execute("INSERT INTO events(request_id,kind,entity_id,payload,created_at,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?)",
                                (request_id, kind, entity_id, encoded, created, previous, event_hash))
            return {"sequence": cursor.lastrowid, "event_hash": event_hash, "duplicate": False}

    def export(self):
        with self.connect() as db:
            rows = db.execute("SELECT sequence,request_id,kind,entity_id,payload,created_at,previous_hash,event_hash FROM events ORDER BY sequence").fetchall()
        keys = ("sequence", "request_id", "kind", "entity_id", "payload", "created_at", "previous_hash", "event_hash")
        result = []
        for row in rows:
            event = dict(zip(keys, row))
            event["payload"] = json.loads(event["payload"])
            result.append(event)
        return {"events": result, "head_sha256": result[-1]["event_hash"] if result else GENESIS}

    def latest(self, kind):
        result = {}
        for event in self.export()["events"]:
            if event["kind"] == kind:
                result[event["entity_id"]] = {**event["payload"], "saved_at": event["created_at"],
                                               "request_id": event["request_id"],
                                               "sequence": event["sequence"], "event_hash": event["event_hash"]}
        return result

    def request(self, request_id):
        with self.connect() as db:
            row = db.execute("SELECT sequence,kind,entity_id,payload,event_hash FROM events WHERE request_id=?", (request_id,)).fetchone()
        return None if row is None else {"sequence": row[0], "kind": row[1], "entity_id": row[2],
                                         "payload": json.loads(row[3]), "event_hash": row[4]}

    def latest_event(self, kind, entity_id):
        with self.connect() as db:
            row = db.execute("SELECT payload,sequence,created_at FROM events WHERE kind=? AND entity_id=? ORDER BY sequence DESC LIMIT 1",
                             (kind, entity_id)).fetchone()
        return None if row is None else {"payload": json.loads(row[0]), "sequence": row[1], "created_at": row[2]}

    def verify(self, expected_head=None):
        exported = self.export()
        previous = GENESIS
        for expected_sequence, event in enumerate(exported["events"], 1):
            calculated = digest([event["request_id"], event["kind"], event["entity_id"], event["payload"],
                                 event["created_at"], previous])
            if event["sequence"] != expected_sequence or event["previous_hash"] != previous or event["event_hash"] != calculated:
                raise ValueError(f"Audit chain failed at sequence {event['sequence']}")
            previous = calculated
        if expected_head is not None and previous != expected_head:
            raise ValueError("Audit head differs from the supplied external anchor")
        return {"valid": True, "events": len(exported["events"]), "head_sha256": previous}

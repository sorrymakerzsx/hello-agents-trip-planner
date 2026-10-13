"""SQLite-backed business sessions for trip planning and human review."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager


VALID_STATUSES = frozenset({
    "RUNNING", "WAITING_FOR_REVIEW", "APPROVED", "REJECTED", "COMPLETED", "FAILED",
})


class SessionConflict(RuntimeError):
    """Raised when another request changed a session before this update."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """Small synchronous SQLite repository.

    Each operation opens its own connection, which is safe when called from
    FastAPI worker threads and keeps the store independent from the event loop.
    """

    def __init__(self, path: str | Path = ".harness/sessions.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        # A short timeout handles concurrent FastAPI requests.  We keep the
        # default journal mode because it also behaves well on Windows volume
        # mounts, where WAL sidecar files can remain locked during shutdown.
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    city TEXT NOT NULL,
                    travel_days INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    draft_plan_json TEXT,
                    final_plan_json TEXT,
                    review_comment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_session_events_run_id
                    ON session_events(run_id, id);
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("request_json", "draft_plan_json", "final_plan_json"):
            if result.get(key):
                result[key[:-5] if key.endswith("_json") else key] = json.loads(result[key])
            result.pop(key, None)
        return result

    def create_session(self, run_id: str, request: dict[str, Any], *, status: str = "RUNNING") -> dict[str, Any]:
        now = _now()
        with self._db() as db:
            db.execute(
                """INSERT INTO sessions
                (run_id, status, city, travel_days, request_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  city=excluded.city, travel_days=excluded.travel_days,
                  request_json=excluded.request_json, updated_at=excluded.updated_at""",
                (run_id, status, request.get("city", ""), request.get("travel_days", 0),
                 json.dumps(request, ensure_ascii=False), now, now),
            )
        return self.get_session(run_id) or {}

    def get_session(self, run_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            return self._decode(db.execute("SELECT * FROM sessions WHERE run_id = ?", (run_id,)).fetchone())

    def update(self, run_id: str, *, status: str | None = None, review_comment: str | None = None,
               draft_plan: dict[str, Any] | None = None, final_plan: dict[str, Any] | None = None) -> dict[str, Any] | None:
        current = self.get_session(run_id)
        if current is None:
            return None
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"unsupported session status: {status}")
        values = {
            "status": status or current["status"],
            "review_comment": review_comment if review_comment is not None else current.get("review_comment", ""),
            "draft_plan_json": json.dumps(draft_plan, ensure_ascii=False) if draft_plan is not None else None,
            "final_plan_json": json.dumps(final_plan, ensure_ascii=False) if final_plan is not None else None,
            "updated_at": _now(),
        }
        with self._db() as db:
            db.execute(
                """UPDATE sessions SET status=?, review_comment=?,
                   draft_plan_json=COALESCE(?, draft_plan_json),
                   final_plan_json=COALESCE(?, final_plan_json), updated_at=?
                   WHERE run_id=?""",
                (values["status"], values["review_comment"], values["draft_plan_json"],
                 values["final_plan_json"], values["updated_at"], run_id),
            )
        return self.get_session(run_id)

    def transition(
        self,
        run_id: str,
        expected_status: str | tuple[str, ...] | list[str] | set[str],
        new_status: str,
        *,
        review_comment: str | None = None,
        draft_plan: dict[str, Any] | None = None,
        final_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically move a session between states.

        The status predicate is part of the UPDATE, so only one concurrent
        approval/rejection can win.  Callers receive SessionConflict for the
        losing request instead of silently overwriting the first decision.
        """
        if new_status not in VALID_STATUSES:
            raise ValueError(f"unsupported session status: {new_status}")
        expected = (expected_status,) if isinstance(expected_status, str) else tuple(expected_status)
        if not expected or any(status not in VALID_STATUSES for status in expected):
            raise ValueError("invalid expected session status")
        current = self.get_session(run_id)
        if current is None:
            raise KeyError(run_id)
        now = _now()
        comment = review_comment if review_comment is not None else current.get("review_comment", "")
        draft_json = json.dumps(draft_plan, ensure_ascii=False) if draft_plan is not None else None
        final_json = json.dumps(final_plan, ensure_ascii=False) if final_plan is not None else None
        placeholders = ",".join("?" for _ in expected)
        with self._db() as db:
            result = db.execute(
                f"""UPDATE sessions SET status=?, review_comment=?,
                    draft_plan_json=COALESCE(?, draft_plan_json),
                    final_plan_json=COALESCE(?, final_plan_json), updated_at=?
                    WHERE run_id=? AND status IN ({placeholders})""",
                (new_status, comment, draft_json, final_json, now, run_id, *expected),
            )
            if result.rowcount != 1:
                raise SessionConflict(f"session {run_id} was already transitioned")
        updated = self.get_session(run_id)
        if updated is None:
            raise KeyError(run_id)
        return updated

    def append_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO session_events (run_id, event_type, data_json, created_at) VALUES (?, ?, ?, ?)",
                (run_id, event_type, json.dumps(data, ensure_ascii=False, default=str), _now()),
            )

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM session_events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [{**dict(row), "data": json.loads(row["data_json"])} for row in rows]

    def delete(self, run_id: str) -> bool:
        with self._db() as db:
            db.execute("DELETE FROM session_events WHERE run_id=?", (run_id,))
            result = db.execute("DELETE FROM sessions WHERE run_id=?", (run_id,))
        return result.rowcount > 0


session_store = SessionStore()

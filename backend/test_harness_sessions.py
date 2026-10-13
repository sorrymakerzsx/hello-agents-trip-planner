"""Fast, dependency-free tests for SQLite session persistence."""

from pathlib import Path
from tempfile import TemporaryDirectory

from app.harness.session_store import SessionStore


def test_session_lifecycle() -> None:
    with TemporaryDirectory() as directory:
        store = SessionStore(Path(directory) / "sessions.db")
        store.create_session("run-1", {"city": "上海", "travel_days": 3})
        store.update("run-1", status="WAITING_FOR_REVIEW", draft_plan={"city": "上海"})
        store.append_event("run-1", "review_required", {"reason": "test"})

        session = store.get_session("run-1")
        assert session is not None
        assert session["status"] == "WAITING_FOR_REVIEW"
        assert session["draft_plan"] == {"city": "上海"}
        assert store.list_events("run-1")[0]["event_type"] == "review_required"


if __name__ == "__main__":
    test_session_lifecycle()
    print("session store tests passed")

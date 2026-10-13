def test_session_lifecycle(tmp_path):
    from app.harness.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions.db")
    store.create_session("run-1", {"city": "上海", "travel_days": 3})
    store.update("run-1", status="WAITING_FOR_REVIEW", draft_plan={"city": "上海"})
    store.append_event("run-1", "review_required", {"reason": "test"})

    session = store.get_session("run-1")
    assert session is not None
    assert session["status"] == "WAITING_FOR_REVIEW"
    assert session["draft_plan"] == {"city": "上海"}
    assert store.list_events("run-1")[0]["event_type"] == "review_required"


def test_atomic_transition_allows_only_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from app.harness.session_store import SessionConflict, SessionStore

    store = SessionStore(tmp_path / "sessions.db")
    store.create_session("run-2", {"city": "上海", "travel_days": 3})
    store.update("run-2", status="WAITING_FOR_REVIEW", draft_plan={"city": "上海"})

    def approve(comment):
        try:
            store.transition("run-2", "WAITING_FOR_REVIEW", "APPROVED", review_comment=comment)
            return "approved"
        except SessionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, ["A", "B"]))

    # One call wins; the other must be rejected by the atomic status predicate.
    assert sorted(results) == ["approved", "conflict"]

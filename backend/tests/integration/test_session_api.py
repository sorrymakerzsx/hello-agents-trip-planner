import asyncio

import httpx
from fastapi import FastAPI

from app.api.routes import trip as trip_routes
from app.harness.session_store import SessionStore
from app.models.schemas import TripPlan


def request_payload(city="上海"):
    return {
        "city": city,
        "start_date": "2026-10-20",
        "end_date": "2026-10-22",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": ["美食"],
        "free_text_input": "",
        "require_human_review": True,
    }


def draft(city="上海"):
    return TripPlan(city=city, start_date="2026-10-20", end_date="2026-10-22", days=[], overall_suggestions="test").model_dump()


class FakeAgent:
    async def plan_trip(self, request):
        return TripPlan(city=request.city, start_date=request.start_date, end_date=request.end_date, days=[], overall_suggestions="regenerated")


async def test_session_api_lifecycle(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions.db")
    monkeypatch.setattr(trip_routes, "session_store", store)
    monkeypatch.setattr(trip_routes, "get_trip_planner_agent", lambda: FakeAgent())
    app = FastAPI()
    app.include_router(trip_routes.router)

    store.create_session("run-1", request_payload())
    store.update("run-1", status="WAITING_FOR_REVIEW", draft_plan=draft())
    store.append_event("run-1", "review_required", {"reason": "test"})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/trip/sessions/run-1")
        assert response.status_code == 200
        assert response.json()["status"] == "WAITING_FOR_REVIEW"
        assert len(response.json()["events"]) == 1

        response = await client.post("/trip/sessions/run-1/approve", json={"comment": "可以"})
        assert response.status_code == 200
        assert response.json()["status"] == "APPROVED"

        response = await client.post("/trip/sessions/run-1/reject", json={"comment": "重复审核"})
        assert response.status_code == 409


async def test_session_api_resume_and_delete(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions.db")
    monkeypatch.setattr(trip_routes, "session_store", store)
    monkeypatch.setattr(trip_routes, "get_trip_planner_agent", lambda: FakeAgent())
    app = FastAPI()
    app.include_router(trip_routes.router)

    store.create_session("run-2", request_payload())
    store.update("run-2", status="WAITING_FOR_REVIEW", draft_plan=draft())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/trip/sessions/run-2/reject", json={"comment": "减少景点"})
        assert response.status_code == 200
        response = await client.post("/trip/sessions/run-2/resume", json={"comment": "只保留两个景点"})
        assert response.status_code == 200
        assert response.json()["status"] == "WAITING_FOR_REVIEW"

        response = await client.delete("/trip/sessions/run-2")
        assert response.status_code == 200
        response = await client.get("/trip/sessions/run-2")
        assert response.status_code == 404


async def test_concurrent_approval_has_one_success(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions.db")
    monkeypatch.setattr(trip_routes, "session_store", store)
    app = FastAPI()
    app.include_router(trip_routes.router)
    store.create_session("run-3", request_payload())
    store.update("run-3", status="WAITING_FOR_REVIEW", draft_plan=draft())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        results = await asyncio.gather(
            client.post("/trip/sessions/run-3/approve", json={"comment": "A"}),
            client.post("/trip/sessions/run-3/approve", json={"comment": "B"}),
        )
        assert sorted(response.status_code for response in results) == [200, 409]

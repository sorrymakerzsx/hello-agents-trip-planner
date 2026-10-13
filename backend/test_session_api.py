"""Interface and race-condition checks for the SQLite session API."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from fastapi import FastAPI

from app.api.routes import trip as trip_routes
from app.harness.session_store import SessionStore
from app.models.schemas import DayPlan, TripPlan


def _request(city: str = "上海") -> dict:
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


def _draft(city: str = "上海") -> dict:
    return TripPlan(
        city=city,
        start_date="2026-10-20",
        end_date="2026-10-22",
        days=[],
        overall_suggestions="测试草稿",
    ).model_dump()


class _FakeAgent:
    async def plan_trip(self, request):
        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=[],
            overall_suggestions="根据审核意见重新生成",
        )


async def _run() -> None:
    with TemporaryDirectory() as directory:
        original_store = trip_routes.session_store
        original_agent_factory = trip_routes.get_trip_planner_agent
        trip_routes.session_store = SessionStore(Path(directory) / "sessions.db")
        trip_routes.get_trip_planner_agent = lambda: _FakeAgent()
        app = FastAPI()
        app.include_router(trip_routes.router)

        try:
            store = trip_routes.session_store
            store.create_session("run-1", _request())
            store.update("run-1", status="WAITING_FOR_REVIEW", draft_plan=_draft())
            store.append_event("run-1", "review_required", {"reason": "test"})

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/trip/sessions/run-1")
                assert response.status_code == 200
                assert response.json()["status"] == "WAITING_FOR_REVIEW"
                assert len(response.json()["events"]) == 1

                response = await client.post("/trip/sessions/run-1/approve", json={"comment": "可以"})
                assert response.status_code == 200
                assert response.json()["status"] == "APPROVED"

                # 同一个会话不能重复审核。
                response = await client.post("/trip/sessions/run-1/reject", json={"comment": "太拥挤"})
                assert response.status_code == 409

                store.create_session("run-2", _request())
                store.update("run-2", status="WAITING_FOR_REVIEW", draft_plan=_draft())
                response = await client.post("/trip/sessions/run-2/reject", json={"comment": "减少景点"})
                assert response.status_code == 200
                assert response.json()["status"] == "REJECTED"

                response = await client.post("/trip/sessions/run-2/resume", json={"comment": "只保留两个景点"})
                assert response.status_code == 200
                assert response.json()["status"] == "WAITING_FOR_REVIEW"

                store.create_session("run-3", _request())
                store.update("run-3", status="WAITING_FOR_REVIEW", draft_plan=_draft())
                results = await asyncio.gather(
                    client.post("/trip/sessions/run-3/approve", json={"comment": "A"}),
                    client.post("/trip/sessions/run-3/approve", json={"comment": "B"}),
                )
                assert sorted(response.status_code for response in results) == [200, 409]

                response = await client.delete("/trip/sessions/run-3")
                assert response.status_code == 200
                response = await client.get("/trip/sessions/run-3")
                assert response.status_code == 404
        finally:
            trip_routes.session_store = original_store
            trip_routes.get_trip_planner_agent = original_agent_factory


if __name__ == "__main__":
    asyncio.run(_run())
    print("session API tests passed")

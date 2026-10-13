"""Run the travel-planning evaluation set.

Default mode is offline and deterministic. It validates the evaluator and the
reporting pipeline without calling an LLM or external map service.

For an end-to-end measurement, run:

    python evals/evaluate_dataset.py --live

Live mode calls the real planner and may consume LLM/map API quota.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.harness.evaluator import EvaluationReport, evaluate_trip_plan
from app.models.schemas import DayPlan, TripPlan, TripRequest, WeatherInfo


DATASET_PATH = Path(__file__).with_name("test_cases.json")


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def fixture_plan(request: TripRequest) -> TripPlan:
    """Create a valid deterministic plan for offline evaluator checks."""
    days = [
        DayPlan(
            date=request.start_date,
            day_index=day_index,
            description=f"{request.city}第{day_index}天行程",
            transportation=request.transportation,
            accommodation=request.accommodation,
        )
        for day_index in range(1, request.travel_days + 1)
    ]
    weather = [
        WeatherInfo(
            date=request.start_date,
            day_weather="晴",
            night_weather="晴",
            day_temp=25,
            night_temp=18,
        )
        for _ in range(request.travel_days)
    ]
    return TripPlan(
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        days=days,
        weather_info=weather,
        overall_suggestions="离线评测样例",
    )


def load_cases() -> list[tuple[str, TripRequest]]:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return [(case["id"], TripRequest.model_validate(case)) for case in payload]


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    return report.to_dict()


async def run_suite(live: bool) -> dict[str, Any]:
    cases = load_cases()
    planner = None
    if live:
        from app.agents.trip_planner_agent import MultiAgentTripPlanner

        planner = MultiAgentTripPlanner()

    results: list[dict[str, Any]] = []
    for case_id, request in cases:
        started = time.perf_counter()
        error = ""
        report: EvaluationReport | None = None
        run_success = False
        try:
            if live:
                plan = await planner.plan_trip(request)
            else:
                plan = fixture_plan(request)
            report = evaluate_trip_plan(request, plan)
            run_success = report.passed
        except Exception as exc:  # keep the suite running after one bad case
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = (time.perf_counter() - started) * 1000
        item: dict[str, Any] = {
            "id": case_id,
            "city": request.city,
            "travel_days": request.travel_days,
            "success": run_success,
            "latency_ms": round(elapsed_ms, 2),
            "error": error,
        }
        if report is not None:
            item["score"] = report.score
            item["checks"] = report_to_dict(report)["checks"]
        if live and planner is not None and planner.last_metrics is not None:
            item["agent_metrics"] = {
                "total_time": planner.last_metrics.total_time,
                "parallel_phase_time": planner.last_metrics.parallel_phase_time,
                "success": planner.last_metrics.success,
            }
        results.append(item)
        print(
            f"[{('PASS' if run_success else 'FAIL')}] {request.city} "
            f"{request.travel_days}d {elapsed_ms:.0f}ms"
            + (f" - {error}" if error else "")
        )

    latencies = [item["latency_ms"] for item in results]
    passed = sum(1 for item in results if item["success"])
    scores = [item["score"] for item in results if "score" in item]
    summary = {
        "mode": "live" if live else "offline",
        "cases": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "success_rate": round(passed / len(results), 3) if results else 0.0,
        "average_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": round(percentile(latencies, 0.95), 2),
        "average_score": round(statistics.mean(scores), 3) if scores else 0.0,
        "results": results,
    }
    print("\nEvaluation summary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate trip planner test cases")
    parser.add_argument(
        "--live",
        action="store_true",
        help="call the real multi-agent planner; may consume API quota",
    )
    args = parser.parse_args()
    asyncio.run(run_suite(live=args.live))


if __name__ == "__main__":
    main()

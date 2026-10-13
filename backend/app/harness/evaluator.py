"""Deterministic quality checks for generated travel plans."""

from dataclasses import asdict, dataclass
from typing import Any

from ..models.schemas import TripPlan, TripRequest


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class EvaluationReport:
    passed: bool
    score: float
    checks: tuple[CheckResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_trip_plan(request: TripRequest, plan: TripPlan) -> EvaluationReport:
    """Run cheap, deterministic checks after the LLM has produced a plan."""
    checks: list[CheckResult] = []

    checks.append(
        CheckResult(
            "city_match",
            plan.city.strip() == request.city.strip(),
            f"计划城市={plan.city!r}，请求城市={request.city!r}",
        )
    )
    checks.append(
        CheckResult(
            "day_count",
            len(plan.days) == request.travel_days,
            f"计划包含 {len(plan.days)} 天，请求为 {request.travel_days} 天",
        )
    )
    checks.append(
        CheckResult(
            "day_indexes",
            [day.day_index for day in plan.days] == list(range(1, request.travel_days + 1)),
            "每日 day_index 应从 1 连续递增",
        )
    )
    checks.append(
        CheckResult(
            "non_empty_descriptions",
            all(day.description.strip() for day in plan.days),
            "每一天都必须有行程描述",
        )
    )
    checks.append(
        CheckResult(
            "weather_coverage",
            len(plan.weather_info) >= request.travel_days,
            f"天气信息 {len(plan.weather_info)} 条，目标至少 {request.travel_days} 条",
        )
    )

    passed_count = sum(check.passed for check in checks)
    return EvaluationReport(
        passed=passed_count == len(checks),
        score=round(passed_count / len(checks), 2) if checks else 0.0,
        checks=tuple(checks),
    )

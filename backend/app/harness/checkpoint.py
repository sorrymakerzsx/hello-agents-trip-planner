"""JSON checkpoint persistence for Harness runs."""

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from .context import RunContext


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _json_safe(value: Any) -> Any:
    """Convert common application objects into JSON-compatible values."""
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class CheckpointStore:
    def __init__(self, directory: str | Path = ".harness/checkpoints") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not _SAFE_RUN_ID.fullmatch(run_id):
            raise ValueError("run_id contains unsupported characters")
        return self.directory / f"{run_id}.json"

    def save(
        self,
        context: RunContext,
        reason: str,
    ) -> Path:
        payload = {
            "schema_version": 1,
            "saved_at": datetime.now().isoformat(),
            "reason": reason,
            "context": _json_safe({
                "run_id": context.run_id,
                "city": context.city,
                "travel_days": context.travel_days,
                "current_phase": context.current_phase,
                "completed_agents": context.completed_agents,
                "agent_results": context.agent_results,
                "errors": context.errors,
                "evaluation": context.evaluation,
                "event_count": context.event_count,
                "last_event_type": context.last_event_type,
                "last_event_data": context.last_event_data,
            }),
        }

        target = self._path(context.run_id)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def load(self, run_id: str) -> RunContext:
        path = self._path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {run_id}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        data = payload["context"]
        return RunContext(
            run_id=data["run_id"],
            city=data["city"],
            travel_days=data["travel_days"],
            current_phase=data.get("current_phase", "created"),
            completed_agents=data.get("completed_agents", []),
            agent_results=data.get("agent_results", {}),
            errors=data.get("errors", []),
            evaluation=data.get("evaluation", {}),
            event_count=data.get("event_count", 0),
            last_event_type=data.get("last_event_type", ""),
            last_event_data=data.get("last_event_data", {}),
        )

    def exists(self, run_id: str) -> bool:
        return self._path(run_id).exists()

    def list_run_ids(self) -> list[str]:
        return sorted(path.stem for path in self.directory.glob("*.json"))

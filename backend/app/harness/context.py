"""State carried through one trip-planning run."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunContext:
    run_id: str
    city: str
    travel_days: int
    current_phase: str = "created"
    completed_agents: list[str] = field(default_factory=list)
    agent_results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    evaluation: dict[str, Any] = field(default_factory=dict)
    event_count: int = 0
    last_event_type: str = ""
    last_event_data: dict[str, Any] = field(default_factory=dict)

    def mark_agent_completed(self, agent_name: str, result: Any) -> None:
        if agent_name not in self.completed_agents:
            self.completed_agents.append(agent_name)
        self.agent_results[agent_name] = result

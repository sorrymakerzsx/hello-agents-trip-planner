"""Lifecycle events emitted by the trip-planning runtime."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class HarnessEvent:
    event_type: str
    run_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    sequence: int = 0


EventHandler = Callable[[HarnessEvent], None]


class EventBus:
    def __init__(self, history_limit: int = 500) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._handlers: list[EventHandler] = []
        self._history_limit = history_limit
        self._sequence: dict[str, int] = {}
        self._history: dict[str, list[HarnessEvent]] = {}

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    def publish(self, event_type: str, run_id: str, **data: Any) -> HarnessEvent:
        sequence = self._sequence.get(run_id, 0) + 1
        self._sequence[run_id] = sequence
        event = HarnessEvent(
            event_type=event_type,
            run_id=run_id,
            data=data,
            sequence=sequence,
        )
        run_history = self._history.setdefault(run_id, [])
        run_history.append(event)
        if len(run_history) > self._history_limit:
            del run_history[:-self._history_limit]
        for handler in self._handlers:
            handler(event)
        return event

    def history(self, run_id: str, after_sequence: int = 0) -> list[HarnessEvent]:
        """Return an in-memory event replay for a run."""
        return [
            event
            for event in self._history.get(run_id, [])
            if event.sequence > after_sequence
        ]


def print_event(event: HarnessEvent) -> None:
    """Default development handler; replace with logging/SSE later."""
    print(
        f"[Harness] run_id={event.run_id} "
        f"seq={event.sequence} type={event.event_type} data={event.data}"
    )

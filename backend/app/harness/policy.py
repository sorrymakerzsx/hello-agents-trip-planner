"""Execution and tool policies for the trip-planning Harness."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPolicy:
    max_attempts: int = 1
    timeout_seconds: float | None = None
    retry_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")


@dataclass(frozen=True)
class ToolPolicy:
    allowed_tools: frozenset[str] | None = None

    def check(self, tool_name: str) -> None:
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            allowed = ", ".join(sorted(self.allowed_tools))
            raise PermissionError(
                f"Tool {tool_name!r} is not allowed. Allowed tools: {allowed}"
            )

"""Task-level runtime orchestration around the existing trip agents."""

import asyncio
from uuid import uuid4
from collections.abc import Awaitable, Callable
from typing import Any

from .context import RunContext
from .checkpoint import CheckpointStore
from .events import EventBus
from .policy import ExecutionPolicy, ToolPolicy


class HarnessRuntime:
    def __init__(
        self,
        checkpoint_store: CheckpointStore | None = None,
        execution_policy: ExecutionPolicy | None = None,
        tool_policy: ToolPolicy | None = None,
    ) -> None:
        self.events = EventBus()
        self.checkpoints = checkpoint_store or CheckpointStore()
        self.execution_policy = execution_policy or ExecutionPolicy()
        self.tool_policy = tool_policy or ToolPolicy()

    def _publish(self, context: RunContext, event_type: str, **data: Any) -> None:
        """Publish an event and persist the latest runtime position."""
        event = self.events.publish(event_type, context.run_id, **data)
        context.event_count = event.sequence
        context.last_event_type = event.event_type
        context.last_event_data = dict(event.data)
        self.checkpoints.save(context, reason=f"event:{event_type}")

    def emit(self, context: RunContext, event_type: str, **data: Any) -> None:
        """Public event entry point for orchestration code outside the runtime."""
        self._publish(context, event_type, **data)

    def start_run(
        self,
        city: str,
        travel_days: int,
        run_id: str | None = None,
        resume: bool = False,
    ) -> RunContext:
        if resume:
            if not run_id:
                raise ValueError("run_id is required when resume=True")
            context = self.checkpoints.load(run_id)
            event_type = "run_resumed"
        else:
            context = RunContext(
                run_id=run_id or uuid4().hex,
                city=city,
                travel_days=travel_days,
            )
            event_type = "run_started"

        self._publish(
            context,
            event_type,
            city=context.city,
            travel_days=context.travel_days,
        )
        return context

    def finish_run(self, context: RunContext, result: object) -> None:
        context.current_phase = "finished"
        self._publish(
            context,
            "run_finished",
            result_type=type(result).__name__,
        )

    def record_evaluation(self, context: RunContext, report: object) -> None:
        """Persist and publish the quality report without changing business output."""
        if hasattr(report, "to_dict"):
            context.evaluation = report.to_dict()
        elif isinstance(report, dict):
            context.evaluation = report
        else:
            context.evaluation = {"value": report}
        self._publish(
            context,
            "evaluation_finished",
            passed=context.evaluation.get("passed"),
            score=context.evaluation.get("score"),
        )

    def fail_run(self, context: RunContext, error: Exception) -> None:
        context.current_phase = "failed"
        error_message = str(error) or type(error).__name__
        context.errors.append(error_message)
        self._publish(
            context,
            "run_failed",
            error=error_message,
        )

    async def run_agent(
        self,
        context: RunContext,
        agent_name: str,
        runner: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Run one business agent while emitting lifecycle events."""
        context.current_phase = f"agent:{agent_name}"
        policy = self.execution_policy
        self._publish(
            context,
            "agent_started",
            agent_name=agent_name,
            max_attempts=policy.max_attempts,
        )

        for attempt in range(1, policy.max_attempts + 1):
            try:
                self._publish(
                    context,
                    "agent_attempt_started",
                    agent_name=agent_name,
                    attempt=attempt,
                )
                pending = runner()
                result = (
                    await asyncio.wait_for(pending, policy.timeout_seconds)
                    if policy.timeout_seconds is not None
                    else await pending
                )

                if getattr(result, "success", True) is False:
                    error = getattr(result, "error", None) or "agent returned an unsuccessful result"
                    if attempt < policy.max_attempts:
                        self._publish(
                            context,
                            "agent_retry",
                            agent_name=agent_name,
                            attempt=attempt,
                            next_attempt=attempt + 1,
                            reason=error,
                        )
                        await asyncio.sleep(policy.retry_delay_seconds)
                        continue

                    context.errors.append(f"{agent_name}: {error}")
                    self.checkpoints.save(context, reason=f"agent_failed:{agent_name}")
                    self._publish(
                        context,
                        "agent_failed",
                        agent_name=agent_name,
                        error=error,
                        attempts=attempt,
                    )
                    return result

                context.mark_agent_completed(agent_name, result)
                self.checkpoints.save(context, reason=f"agent_finished:{agent_name}")
                self._publish(
                    context,
                    "agent_finished",
                    agent_name=agent_name,
                    success=True,
                    attempts=attempt,
                )
                return result
            except Exception as exc:
                error_message = str(exc) or type(exc).__name__
                if attempt < policy.max_attempts:
                    self._publish(
                        context,
                        "agent_retry",
                        agent_name=agent_name,
                        attempt=attempt,
                        next_attempt=attempt + 1,
                        reason=error_message,
                    )
                    await asyncio.sleep(policy.retry_delay_seconds)
                    continue

                context.errors.append(f"{agent_name}: {error_message}")
                self.checkpoints.save(context, reason=f"agent_failed:{agent_name}")
                self._publish(
                    context,
                    "agent_failed",
                    agent_name=agent_name,
                    error=error_message,
                    attempts=attempt,
                )
                raise

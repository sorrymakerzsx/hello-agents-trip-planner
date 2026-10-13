import asyncio

import pytest

from app.harness.policy import ExecutionPolicy, ToolPolicy
from app.harness.checkpoint import CheckpointStore
from app.harness.runtime import HarnessRuntime


@pytest.mark.asyncio
async def test_agent_retries_then_finishes(tmp_path):
    attempts = 0
    runtime = HarnessRuntime(
        checkpoint_store=CheckpointStore(tmp_path),
        execution_policy=ExecutionPolicy(max_attempts=2, timeout_seconds=0.2, retry_delay_seconds=0),
    )
    context = runtime.start_run("北京", 3)

    async def flaky_agent():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        return {"status": "ok", "attempt": attempts}

    result = await runtime.run_agent(context, "weather", flaky_agent)
    assert result == {"status": "ok", "attempt": 2}
    assert context.completed_agents == ["weather"]
    assert context.last_event_type == "agent_finished"
    assert "agent_retry" in [event.event_type for event in runtime.events.history(context.run_id)]


@pytest.mark.asyncio
async def test_agent_timeout_marks_run_failed(tmp_path):
    runtime = HarnessRuntime(
        checkpoint_store=CheckpointStore(tmp_path),
        execution_policy=ExecutionPolicy(max_attempts=1, timeout_seconds=0.01, retry_delay_seconds=0),
    )
    context = runtime.start_run("北京", 1)

    async def slow_agent():
        await asyncio.sleep(0.05)

    with pytest.raises(TimeoutError):
        await runtime.run_agent(context, "slow_agent", slow_agent)

    runtime.fail_run(context, TimeoutError("timeout"))
    assert context.current_phase == "failed"
    assert context.last_event_type == "run_failed"


def test_tool_policy_rejects_unauthorized_tool():
    policy = ToolPolicy(allowed_tools=frozenset({"amap_maps_weather"}))
    policy.check("amap_maps_weather")
    with pytest.raises(PermissionError):
        policy.check("filesystem_delete")

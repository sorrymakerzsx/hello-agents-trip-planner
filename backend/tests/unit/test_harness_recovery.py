import pytest

from app.harness.checkpoint import CheckpointStore
from app.harness.policy import ExecutionPolicy
from app.harness.runtime import HarnessRuntime


@pytest.mark.asyncio
async def test_checkpoint_can_resume_completed_agent(tmp_path):
    runtime = HarnessRuntime(
        checkpoint_store=CheckpointStore(tmp_path),
        execution_policy=ExecutionPolicy(max_attempts=2, retry_delay_seconds=0),
    )
    context = runtime.start_run("上海", 3, run_id="recovery-demo")
    attempts = 0

    async def flaky_agent():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        return {"status": "ok"}

    assert await runtime.run_agent(context, "weather", flaky_agent) == {"status": "ok"}
    resumed = runtime.start_run("上海", 3, run_id="recovery-demo", resume=True)

    assert attempts == 2
    assert resumed.completed_agents == ["weather"]
    assert resumed.agent_results["weather"] == {"status": "ok"}
    event_types = [event.event_type for event in runtime.events.history(context.run_id)]
    assert "agent_retry" in event_types
    assert event_types[-1] == "run_resumed"

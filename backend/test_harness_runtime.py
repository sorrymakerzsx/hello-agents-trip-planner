import asyncio

from app.harness.runtime import HarnessRuntime
from app.harness.events import print_event
from app.harness.policy import ExecutionPolicy
from app.harness.policy import ToolPolicy


async def main():
    attempts = {"retry": 0}
    runtime = HarnessRuntime(
        execution_policy=ExecutionPolicy(
            max_attempts=2,
            timeout_seconds=0.2,
            retry_delay_seconds=0,
        )
    )
    runtime.events.subscribe(print_event)

    context = runtime.start_run(
        city="北京",
        travel_days=3,
    )

    # async def fake_agent():
    #     await asyncio.sleep(0.1)
    #     return {"status": "ok"}
    async def fake_agent():
        attempts["retry"] += 1
        if attempts["retry"] == 1:
            raise RuntimeError("模拟第一次失败")
        return {"status": "ok", "attempt": attempts["retry"]}

    try:
        result = await runtime.run_agent(
            context=context,
            agent_name="weather",
            runner=fake_agent,
        )
        runtime.finish_run(context, result)
    except Exception as exc:
        runtime.fail_run(context, exc)

    print("\n最终上下文：")
    print(context)

    timeout_context = runtime.start_run(city="北京", travel_days=3)

    async def slow_agent():
        await asyncio.sleep(1)
        return {"status": "too slow"}

    try:
        await runtime.run_agent(
            context=timeout_context,
            agent_name="slow_agent",
            runner=slow_agent,
        )
    except Exception as exc:
        runtime.fail_run(timeout_context, exc)

    print("\n超时上下文：")
    print(timeout_context)

    tool_policy = ToolPolicy(
        allowed_tools=frozenset({"amap_maps_weather"})
    )
    tool_policy.check("amap_maps_weather")
    try:
        tool_policy.check("filesystem_delete")
    except PermissionError as exc:
        print("\n工具权限检查：")
        print(f"已阻止未授权工具：{exc}")


if __name__ == "__main__":
    asyncio.run(main())

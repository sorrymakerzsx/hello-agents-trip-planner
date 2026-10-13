"""旅行规划API路由"""

import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ...models.schemas import (
    TripRequest,
    TripPlanResponse,
    ErrorResponse,
    ReviewRequest,
    SessionStatusResponse,
)
from ...agents.trip_planner_agent import get_trip_planner_agent
from ...harness.session_store import SessionConflict, session_store

router = APIRouter(prefix="/trip", tags=["旅行规划"])


class ParseRequest(BaseModel):
    """自然语言解析请求"""
    text: str = Field(..., description="用户自由输入的旅行描述", example="7月10-12日去北京，喜欢美食和历史文化，想去故宫")


@router.post(
    "/parse",
    summary="自然语言解析",
    description="将用户的自然语言描述解析为结构化旅行参数"
)
async def parse_natural_language(request: ParseRequest):
    """
    自然语言 → 结构化参数

    输入: "7月10-12日去北京，喜欢美食，想去故宫"
    输出: {city, start_date, end_date, preferences, free_text_input, ...}
    """
    agent = await asyncio.to_thread(get_trip_planner_agent)
    parsed = await agent.parse_natural_language(request.text)
    return {"success": True, "data": parsed}


@router.post(
    "/plan/stream",
    summary="生成旅行计划 (SSE流式推送)",
    description="通过Server-Sent Events实时推送多Agent协作进度"
)
async def plan_trip_stream(request: TripRequest):
    """
    流式生成旅行计划

    通过 SSE (Server-Sent Events) 实时推送每个Agent的执行状态:
    - phase: 阶段切换 (parallel/planning)
    - agent_start: Agent开始执行
    - agent_done: Agent完成,包含耗时和摘要
    - complete: 最终旅行计划JSON
    - metrics: 性能指标

    前端使用 EventSource 或 fetch + ReadableStream 消费此端点。
    """
    async def event_generator():
        agent = await asyncio.to_thread(get_trip_planner_agent)
        session_id = None

        print(f"\n{'='*60}")
        print(f"📥 收到SSE流式规划请求:")
        print(f"   城市: {request.city}")
        print(f"   日期: {request.start_date} - {request.end_date}")
        print(f"   天数: {request.travel_days}")
        print(f"{'='*60}\n")

        async for event in agent.plan_trip_stream(request):
            context = getattr(agent, "last_run_context", None)
            if context is not None and session_id is None:
                session_id = context.run_id
                await asyncio.to_thread(session_store.create_session, session_id, request.model_dump())
            if session_id is not None and event["event"] == "complete":
                await asyncio.to_thread(
                    session_store.update,
                    session_id,
                    status="WAITING_FOR_REVIEW" if request.require_human_review else "COMPLETED",
                    draft_plan=event["data"] if request.require_human_review else None,
                    final_plan=None if request.require_human_review else event["data"],
                )
                if request.require_human_review:
                    await asyncio.to_thread(session_store.append_event, session_id, "review_required", {"reason": "human review requested"})
            if session_id is not None and event["event"] == "error":
                await asyncio.to_thread(
                    session_store.update,
                    session_id,
                    status="FAILED",
                    review_comment=event["data"].get("message", "stream execution failed"),
                )
            if session_id is not None:
                await asyncio.to_thread(session_store.append_event, session_id, event["event"], event["data"])
            event_type = event["event"]
            data = event["data"]
            # SSE 格式: "event: <type>\ndata: <json>\n\n"
            yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        print("✅ SSE流式规划完成\n")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划 (并行Agent执行)",
    description="根据用户输入的旅行需求,使用多Agent并行协作生成详细的旅行计划"
)
async def plan_trip(request: TripRequest):
    """
    生成旅行计划

    景点搜索、天气查询、酒店推荐三个Agent并行执行，
    行程规划Agent等待前三步完成后串行执行。

    Args:
        request: 旅行请求参数

    Returns:
        旅行计划响应 (含性能指标)
    """
    try:
        print(f"\n{'='*60}")
        print(f"📥 收到旅行规划请求:")
        print(f"   城市: {request.city}")
        print(f"   日期: {request.start_date} - {request.end_date}")
        print(f"   天数: {request.travel_days}")
        print(f"{'='*60}\n")

        # 获取Agent实例
        print("🔄 获取多智能体系统实例...")
        agent = await asyncio.to_thread(get_trip_planner_agent)

        # 并行生成旅行计划 (await异步方法)
        print("🚀 开始【并行】生成旅行计划...")
        trip_plan = await agent.plan_trip(request)

        run_id = (
            agent.last_run_context.run_id
            if getattr(agent, "last_run_context", None)
            else None
        )
        if run_id:
            session_store.create_session(run_id, request.model_dump())
            if request.require_human_review:
                session_store.update(run_id, status="WAITING_FOR_REVIEW", draft_plan=trip_plan.model_dump())
                session_store.append_event(run_id, "review_required", {"reason": "human review requested"})
            else:
                session_store.update(run_id, status="COMPLETED", final_plan=trip_plan.model_dump())
                session_store.append_event(run_id, "session_completed", {})

        session_status = "WAITING_FOR_REVIEW" if request.require_human_review else "COMPLETED"

        # 构建带性能指标的消息
        message = "旅行计划生成成功"
        if agent.last_metrics:
            m = agent.last_metrics
            message += (
                f" | 总耗时{m.total_time:.1f}s"
                f" | 并行阶段{m.parallel_phase_time:.1f}s"
                f" | 加速比{m.speedup:.2f}x"
            )

        print("✅ 旅行计划生成成功,准备返回响应\n")

        return TripPlanResponse(
            success=True,
            message=message,
            data=trip_plan,
            run_id=run_id,
            evaluation=(
                agent.last_run_context.evaluation
                if getattr(agent, "last_run_context", None)
                else None
            ),
            status=session_status,
        )

    except Exception as e:
        print(f"❌ 生成旅行计划失败: {str(e)}")
        failed_context = getattr(locals().get("agent"), "last_run_context", None)
        if failed_context is not None:
            try:
                session_store.create_session(failed_context.run_id, request.model_dump())
                session_store.update(failed_context.run_id, status="FAILED", review_comment=str(e))
                session_store.append_event(failed_context.run_id, "session_failed", {"error": str(e)})
            except Exception:
                pass
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"生成旅行计划失败: {str(e)}"
        )


@router.get(
    "/sessions/{run_id}",
    response_model=SessionStatusResponse,
    summary="查询 SQLite 会话状态",
)
async def get_session(run_id: str):
    session = await asyncio.to_thread(session_store.get_session, run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    events = await asyncio.to_thread(session_store.list_events, run_id)
    return {"run_id": run_id, "status": session["status"], "session": session, "events": events}


@router.post("/sessions/{run_id}/approve")
async def approve_session(run_id: str, request: ReviewRequest | None = None):
    current = await asyncio.to_thread(session_store.get_session, run_id)
    if current is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if current["status"] != "WAITING_FOR_REVIEW":
        raise HTTPException(status_code=409, detail=f"当前状态不可审核: {current['status']}")
    final_plan = current.get("draft_plan")
    if not final_plan:
        raise HTTPException(status_code=409, detail="会话没有可审核的草稿")
    try:
        updated = await asyncio.to_thread(
            session_store.transition, run_id, "WAITING_FOR_REVIEW", "APPROVED",
            review_comment=(request.comment if request else ""), final_plan=final_plan,
        )
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await asyncio.to_thread(session_store.append_event, run_id, "review_approved", {"comment": (request.comment if request else "")})
    return {"success": True, "status": "APPROVED", "data": final_plan, "session": updated}


@router.post("/sessions/{run_id}/reject")
async def reject_session(run_id: str, request: ReviewRequest):
    current = await asyncio.to_thread(session_store.get_session, run_id)
    if current is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if current["status"] != "WAITING_FOR_REVIEW":
        raise HTTPException(status_code=409, detail=f"当前状态不可驳回: {current['status']}")
    try:
        updated = await asyncio.to_thread(
            session_store.transition, run_id, "WAITING_FOR_REVIEW", "REJECTED",
            review_comment=request.comment,
        )
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await asyncio.to_thread(session_store.append_event, run_id, "review_rejected", {"comment": request.comment})
    return {"success": True, "status": "REJECTED", "session": updated}


@router.delete("/sessions/{run_id}")
async def delete_session(run_id: str):
    deleted = await asyncio.to_thread(session_store.delete, run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True, "run_id": run_id}


@router.post("/sessions/{run_id}/resume")
async def resume_session(run_id: str, request: ReviewRequest):
    """Regenerate a rejected draft with the human feedback included."""
    current = await asyncio.to_thread(session_store.get_session, run_id)
    if current is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if current["status"] not in {"REJECTED", "WAITING_FOR_REVIEW"}:
        raise HTTPException(status_code=409, detail=f"当前状态不可恢复: {current['status']}")

    payload = dict(current["request"])
    payload["run_id"] = run_id
    payload["resume"] = False
    payload["require_human_review"] = True
    previous = payload.get("free_text_input") or ""
    payload["free_text_input"] = f"{previous}\n人工审核意见：{request.comment}".strip()
    try:
        trip_request = TripRequest.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"会话请求数据无效: {exc}") from exc
    agent = await asyncio.to_thread(get_trip_planner_agent)
    try:
        plan = await agent.plan_trip(trip_request)
        updated = await asyncio.to_thread(
            session_store.transition, run_id, ("REJECTED", "WAITING_FOR_REVIEW"), "WAITING_FOR_REVIEW",
            review_comment=request.comment, draft_plan=plan.model_dump(),
        )
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        await asyncio.to_thread(session_store.update, run_id, status="FAILED", review_comment=str(exc))
        await asyncio.to_thread(session_store.append_event, run_id, "session_failed", {"error": str(exc)})
        raise HTTPException(status_code=502, detail="重新生成行程失败，请稍后重试") from exc
    await asyncio.to_thread(session_store.append_event, run_id, "review_resume_requested", {"comment": request.comment})
    return {"success": True, "status": "WAITING_FOR_REVIEW", "data": plan.model_dump(), "session": updated}


@router.get(
    "/metrics",
    summary="获取性能指标",
    description="获取最近一次规划的性能指标和所有历史指标汇总"
)
async def get_metrics():
    """获取Agent执行性能指标"""
    agent = await asyncio.to_thread(get_trip_planner_agent)

    last = agent.last_metrics
    all_m = agent.all_metrics

    return {
        "last_metrics": {
            "city": last.city,
            "travel_days": last.travel_days,
            "step1_attraction_time": last.step1_attraction_time,
            "step2_weather_time": last.step2_weather_time,
            "step3_hotel_time": last.step3_hotel_time,
            "step4_planner_time": last.step4_planner_time,
            "parallel_phase_time": last.parallel_phase_time,
            "serial_equivalent": last.serial_equivalent,
            "speedup": last.speedup,
            "total_time": last.total_time,
            "total_llm_calls": last.total_llm_calls,
            "success": last.success,
            "error_message": last.error_message
        } if last else None,
        "summary": {
            "total_requests": len(all_m),
            "successful": sum(1 for m in all_m if m.success),
            "failed": sum(1 for m in all_m if not m.success),
            "avg_speedup": (
                sum(m.speedup for m in all_m) / len(all_m)
                if all_m else 0
            ),
            "avg_total_time": (
                sum(m.total_time for m in all_m) / len(all_m)
                if all_m else 0
            )
        } if all_m else None
    }


@router.get(
    "/health",
    summary="健康检查",
    description="检查旅行规划服务是否正常"
)
async def health_check():
    """健康检查"""
    try:
        # 检查Agent是否可用
        agent = await asyncio.to_thread(get_trip_planner_agent)

        return {
            "status": "healthy",
            "service": "trip-planner",
            "execution_mode": "parallel",
            "agents_count": 4,
            "total_requests_processed": len(agent.all_metrics)
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}"
        )

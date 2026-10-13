"""
基准测试脚本 — 对比串行 vs 并行 Agent 执行性能

用法:
    cd backend
    python benchmark.py

该脚本会:
1. 先模拟串行执行 (3个Agent依次调用) 并计时
2. 再实际调用并行API (3个Agent同时执行) 并计时
3. 输出对比报告
"""

import time
import asyncio
import json
import requests
from app.config import get_settings
from app.agents.trip_planner_agent import (
    MultiAgentTripPlanner,
    ExecutionMetrics,
    StepResult
)


# ─────────────────────────────────────────────────────────────
# 测试用例
# ─────────────────────────────────────────────────────────────
TEST_CASES = [
    {"city": "北京", "travel_days": 2, "desc": "北京 2日游 (小行程)"},
    {"city": "上海", "travel_days": 3, "desc": "上海 3日游 (中行程)"},
]


def make_request(city: str, travel_days: int):
    """构造标准测试请求"""
    return type('TripRequest', (), {
        'city': city,
        'start_date': '2026-07-10',
        'end_date': f'2026-07-{10 + travel_days - 1}',
        'travel_days': travel_days,
        'transportation': '公共交通',
        'accommodation': '经济型酒店',
        'preferences': ['历史文化', '美食'],
        'free_text_input': ''
    })()


# ─────────────────────────────────────────────────────────────
# 串行模拟 (保留旧逻辑用于对比)
# ─────────────────────────────────────────────────────────────
async def run_serial(planner: MultiAgentTripPlanner, request) -> dict:
    """模拟串行执行 — 步骤1→2→3依次调用"""
    times = {}
    total_start = time.time()

    # Step 1
    t0 = time.time()
    query1 = planner._build_attraction_query(request)
    r1 = await asyncio.to_thread(planner.attraction_agent.run, query1)
    times['step1'] = time.time() - t0

    # Step 2 (等step1完成)
    t0 = time.time()
    query2 = f"请查询{request.city}的天气信息"
    r2 = await asyncio.to_thread(planner.weather_agent.run, query2)
    times['step2'] = time.time() - t0

    # Step 3 (等step2完成)
    t0 = time.time()
    query3 = f"请搜索{request.city}的{request.accommodation}酒店"
    r3 = await asyncio.to_thread(planner.hotel_agent.run, query3)
    times['step3'] = time.time() - t0

    # Step 4
    t0 = time.time()
    query4 = planner._build_planner_query(request, r1, r2, r3)
    r4 = await asyncio.to_thread(planner.planner_agent.run, query4)
    times['step4'] = time.time() - t0

    times['total'] = time.time() - total_start
    times['parallel_phase_serial'] = times['step1'] + times['step2'] + times['step3']

    return {
        'times': times,
        'responses': (r1, r2, r3, r4)
    }


# ─────────────────────────────────────────────────────────────
# 并行执行 (新架构 — 实际API调用)
# ─────────────────────────────────────────────────────────────
async def run_parallel(planner: MultiAgentTripPlanner, request):
    """运行并行执行并获取指标"""
    trip_plan = await planner.plan_trip(request)
    return planner.last_metrics


# ─────────────────────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────────────────────
async def main():
    print("\n" + "=" * 70)
    print("🏁 多Agent执行模式性能对比基准测试")
    print("=" * 70)

    # 初始化规划器
    print("\n🔧 初始化 MultiAgentTripPlanner...")
    planner = MultiAgentTripPlanner()

    all_results = []

    for i, case in enumerate(TEST_CASES):
        request = make_request(case['city'], case['travel_days'])

        print(f"\n{'─' * 70}")
        print(f"📋 测试用例 {i+1}: {case['desc']}")
        print(f"{'─' * 70}")

        # ── 串行模拟 ──
        print("\n🔴 [串行模式] 步骤1→步骤2→步骤3→步骤4...")
        serial_result = await run_serial(planner, request)
        st = serial_result['times']

        print(f"   步骤1 (景点): {st['step1']:.1f}s")
        print(f"   步骤2 (天气): {st['step2']:.1f}s")
        print(f"   步骤3 (酒店): {st['step3']:.1f}s")
        print(f"   步骤4 (规划): {st['step4']:.1f}s")
        print(f"   串行阶段1-3合计: {st['parallel_phase_serial']:.1f}s")
        print(f"   总耗时: {st['total']:.1f}s")

        # ── 并行执行 ──
        print("\n🟢 [并行模式] 步骤1‖步骤2‖步骤3 → 步骤4...")
        parallel_metrics = await run_parallel(planner, request)
        pm = parallel_metrics

        print(f"   步骤1 (景点): {pm.step1_attraction_time:.1f}s")
        print(f"   步骤2 (天气): {pm.step2_weather_time:.1f}s")
        print(f"   步骤3 (酒店): {pm.step3_hotel_time:.1f}s")
        print(f"   步骤4 (规划): {pm.step4_planner_time:.1f}s")
        print(f"   并行阶段实际: {pm.parallel_phase_time:.1f}s")
        print(f"   总耗时: {pm.total_time:.1f}s")

        # ── 对比 ──
        speedup = st['parallel_phase_serial'] / pm.parallel_phase_time if pm.parallel_phase_time > 0 else 1
        total_improvement = (st['total'] - pm.total_time) / st['total'] * 100

        all_results.append({
            'case': case['desc'],
            'serial_phase_time': st['parallel_phase_serial'],
            'parallel_phase_time': pm.parallel_phase_time,
            'serial_total': st['total'],
            'parallel_total': pm.total_time,
            'speedup': speedup,
            'total_improvement_pct': total_improvement
        })

    # ── 汇总报告 ──
    print(f"\n{'=' * 70}")
    print("📊 性能对比汇总")
    print(f"{'=' * 70}")
    print(f"{'测试用例':<22} {'串行阶段':>8} {'并行阶段':>8} {'加速比':>8} {'总耗时改善':>10}")
    print(f"{'─' * 70}")
    for r in all_results:
        print(
            f"{r['case']:<22} "
            f"{r['serial_phase_time']:>7.1f}s "
            f"{r['parallel_phase_time']:>7.1f}s "
            f"{r['speedup']:>7.2f}x "
            f"{r['total_improvement_pct']:>9.0f}%"
        )

    avg_speedup = sum(r['speedup'] for r in all_results) / len(all_results)
    avg_improvement = sum(r['total_improvement_pct'] for r in all_results) / len(all_results)
    print(f"{'─' * 70}")
    print(f"  平均加速比: {avg_speedup:.2f}x")
    print(f"  平均总耗时改善: {avg_improvement:.0f}%")
    print(f"{'=' * 70}\n")

    print("💡 关键解释:")
    print("  - 加速比 = 串行阶段耗时 / 并行阶段耗时")
    print("  - 步骤1(景点)、步骤2(天气)、步骤3(酒店) 互不依赖，适合并行")
    print("  - 步骤4(行程规划) 依赖前三步结果，必须串行等待")
    print("  - 行程越长，步骤4占比越大，但前3步的并行优化始终有效\n")


if __name__ == "__main__":
    asyncio.run(main())

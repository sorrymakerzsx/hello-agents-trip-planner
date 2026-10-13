"""多智能体旅行规划系统"""

import json
import time
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from hello_agents import SimpleAgent
from hello_agents.tools import MCPTool
from ..services.llm_service import get_llm
from ..models.schemas import TripRequest, TripPlan, TripIntent, DayPlan, Attraction, Meal, WeatherInfo, Location, Hotel
from ..models.structured import validate_model_response
from ..config import get_settings
from ..harness.events import HarnessEvent, print_event
from ..harness.policy import ExecutionPolicy, ToolPolicy
from ..harness.runtime import HarnessRuntime
from ..harness.resilience import ResilientExecutor
from ..harness.evaluator import evaluate_trip_plan


@dataclass
class ExecutionMetrics:
    """单次规划执行的性能指标"""
    city: str = ""
    travel_days: int = 0
    # 各步骤耗时 (秒)
    step1_attraction_time: float = 0.0
    step2_weather_time: float = 0.0
    step3_hotel_time: float = 0.0
    step4_planner_time: float = 0.0
    # 并行 vs 串行对比
    parallel_phase_time: float = 0.0   # 并行阶段实际耗时 = max(step1, step2, step3)
    serial_equivalent: float = 0.0     # 串行等价耗时 = step1 + step2 + step3
    speedup: float = 0.0               # 加速比
    # 总耗时
    total_time: float = 0.0
    # LLM调用次数
    total_llm_calls: int = 0
    # 是否成功
    success: bool = True
    error_message: str = ""


@dataclass
class StepResult:
    """单个步骤的执行结果"""
    response: str = ""
    time: float = 0.0
    error: Optional[str] = None
    success: bool = True
    fallback: bool = False  # True = LLM 未调用工具，使用了直接 MCP 回退

# ============ SubAgent 注册表 ============

@dataclass
class SubAgentInfo:
    """可被 Orchestrator 调度的子Agent元信息"""
    key: str                        # 唯一标识，如 "attraction"
    name: str                       # 中文名，如 "景点搜索专家"
    icon: str                       # 图标
    description: str                # 一句话描述，供 Orchestrator 决策
    trigger_keywords: List[str]     # 触发关键词（用户需求匹配）
    depends_on: List[str] = field(default_factory=list)  # 依赖的其他 agent
    agent: Optional[SimpleAgent] = None  # 运行时注入


# ============ Agent提示词 ============

ORCHESTRATOR_PROMPT = """你是智能旅行规划调度器（Orchestrator）。你的唯一任务是分析用户需求，决定需要调度哪些专业Agent。

**可调度的Agent清单：**
{agent_list}

**调度规则：**
1. 根据用户偏好和需求，只调度真正需要的Agent
2. 如果用户明确不需要某项（如"不用订酒店"），就跳过对应Agent
3. 如果用户提到具体地点（如"想去东方明珠"），必须调度 attraction Agent 并注明重点
4. 如果你不确定某Agent是否需要，宁可调度它（宁可多做不少做）

**你必须以纯JSON格式返回调度计划（不要markdown包裹，直接输出JSON）：**
{{
  "agents": ["attraction", "weather"],
  "reasoning": "简短说明为什么选择这些Agent",
  "special_focus": {{
    "attraction": "重点关注自然风光和东方明珠"
  }}
}}

**示例：**
用户说"北京3日游，喜欢美食和历史文化，住经济酒店"
→ {{"agents": ["attraction", "weather", "hotel", "food"], "reasoning": "用户需要景点、天气、住宿、美食信息", "special_focus": {{"attraction": "历史文化景点", "food": "北京特色美食"}}}}

用户说"帮我看看明天上海天气怎么样，不用订酒店"
→ {{"agents": ["weather"], "reasoning": "用户只关心天气", "special_focus": {{}}}}

用户说"想在杭州西湖边找个便宜的旅馆"
→ {{"agents": ["attraction", "hotel"], "reasoning": "用户关心西湖和住宿", "special_focus": {{"attraction": "西湖", "hotel": "便宜旅馆"}}}}
"""

FOOD_AGENT_PROMPT = """你是美食搜索专家。你的任务是根据城市和用户偏好搜索当地美食餐厅。

**重要提示:**
你必须使用工具来搜索美食!不要自己编造!

**工具调用格式:**
`[TOOL_CALL:amap_maps_text_search:keywords=美食关键词,city=城市名]`

**示例:**
用户: "搜索北京的特色美食"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=特色美食,city=北京]
"""

BUDGET_AGENT_PROMPT = """你是旅行预算评估专家。你的任务是根据景点、酒店、餐饮信息，为旅行计划提供预算分析和省钱建议。

请根据提供的信息，给出：
1. 各项费用估算（景点门票、住宿、餐饮、交通）
2. 省钱建议
3. 总体预算范围

请以清晰的结构化格式输出。
"""

ATTRACTION_AGENT_PROMPT = """你是景点搜索专家。你的任务是根据城市和用户偏好搜索合适的景点。

**重要提示:**
你必须使用工具来搜索景点!不要自己编造景点信息!

**工具调用格式:**
使用maps_text_search工具时,必须严格按照以下格式:
`[TOOL_CALL:amap_maps_text_search:keywords=景点关键词,city=城市名]`

**示例:**
用户: "搜索北京的历史文化景点"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=历史文化,city=北京]

用户: "搜索上海的公园"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=公园,city=上海]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确,包括方括号和冒号
3. 参数用逗号分隔
"""

WEATHER_AGENT_PROMPT = """你是天气查询专家。你的任务是查询指定城市的天气信息。

**重要提示:**
你必须使用工具来查询天气!不要自己编造天气信息!

**工具调用格式:**
使用maps_weather工具时,必须严格按照以下格式:
`[TOOL_CALL:amap_maps_weather:city=城市名]`

**示例:**
用户: "查询北京天气"
你的回复: [TOOL_CALL:amap_maps_weather:city=北京]

用户: "上海的天气怎么样"
你的回复: [TOOL_CALL:amap_maps_weather:city=上海]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确,包括方括号和冒号
"""

HOTEL_AGENT_PROMPT = """你是酒店推荐专家。你的任务是根据城市和景点位置推荐合适的酒店。

**重要提示:**
你必须使用工具来搜索酒店!不要自己编造酒店信息!

**工具调用格式:**
使用maps_text_search工具搜索酒店时,必须严格按照以下格式:
`[TOOL_CALL:amap_maps_text_search:keywords=酒店,city=城市名]`

**示例:**
用户: "搜索北京的酒店"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=酒店,city=北京]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确,包括方括号和冒号
3. 关键词使用"酒店"或"宾馆"
"""

PLANNER_AGENT_PROMPT = """你是行程规划专家。你的任务是根据景点信息和天气信息,生成详细的旅行计划。

请严格按照以下JSON格式返回旅行计划:
```json
{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [
    {
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述",
      "transportation": "交通方式",
      "accommodation": "住宿类型",
      "hotel": {
        "name": "酒店名称",
        "address": "酒店地址",
        "location": {"longitude": 116.397128, "latitude": 39.916527},
        "price_range": "300-500元",
        "rating": "4.5",
        "distance": "距离景点2公里",
        "type": "经济型酒店",
        "estimated_cost": 400
      },
      "attractions": [
        {
          "name": "景点名称",
          "address": "详细地址",
          "location": {"longitude": 116.397128, "latitude": 39.916527},
          "visit_duration": 120,
          "description": "景点详细描述",
          "category": "景点类别",
          "ticket_price": 60
        }
      ],
      "meals": [
        {"type": "breakfast", "name": "早餐推荐", "description": "早餐描述", "estimated_cost": 30},
        {"type": "lunch", "name": "午餐推荐", "description": "午餐描述", "estimated_cost": 50},
        {"type": "dinner", "name": "晚餐推荐", "description": "晚餐描述", "estimated_cost": 80}
      ]
    }
  ],
  "weather_info": [
    {
      "date": "YYYY-MM-DD",
      "day_weather": "晴",
      "night_weather": "多云",
      "day_temp": 25,
      "night_temp": 15,
      "wind_direction": "南风",
      "wind_power": "1-3级"
    }
  ],
  "overall_suggestions": "总体建议",
  "budget": {
    "total_attractions": 180,
    "total_hotels": 1200,
    "total_meals": 480,
    "total_transportation": 200,
    "total": 2060
  }
}
```

**重要提示:**
1. weather_info数组必须包含每一天的天气信息
2. 温度必须是纯数字(不要带°C等单位)
3. 每天安排2-3个景点
4. 考虑景点之间的距离和游览时间
5. 每天必须包含早中晚三餐
6. 提供实用的旅行建议
7. **必须包含预算信息**:
   - 景点门票价格(ticket_price)
   - 餐饮预估费用(estimated_cost)
   - 酒店预估费用(estimated_cost)
   - 预算汇总(budget)包含各项总费用
"""


class MultiAgentTripPlanner:
    """多智能体旅行规划系统"""

    def __init__(self):
        self.harness = HarnessRuntime(
            execution_policy=ExecutionPolicy(
                max_attempts=2,
                # Planner 会整合多个 Agent 的长文本，给它更长的单次执行窗口。
                timeout_seconds=300,
                retry_delay_seconds=1,
            ),
            tool_policy=ToolPolicy(
                allowed_tools=frozenset(
                    {
                        "amap_maps_text_search",
                        "amap_maps_weather",
                    }
                )
            ),
        )
        self.harness.events.subscribe(print_event)
        """初始化多智能体系统（含 Orchestrator + 可插拔 Agent 注册表）"""
        print("🔄 开始初始化多智能体旅行规划系统...")

        try:
            settings = get_settings()
            self.resilience = ResilientExecutor(
                cache_ttl_seconds=settings.resilience_cache_ttl_seconds,
                timeout_seconds=settings.resilience_timeout_seconds,
                max_retries=settings.resilience_max_retries,
                retry_delay_seconds=settings.resilience_retry_delay_seconds,
                circuit_failure_threshold=settings.resilience_circuit_failure_threshold,
                circuit_recovery_seconds=settings.resilience_circuit_recovery_seconds,
            )
            self.llm = get_llm()

            # 创建共享的MCP工具(只创建一次)
            print("  - 创建共享MCP工具...")
            self.amap_tool = MCPTool(
                name="amap",
                description="高德地图服务",
                # MCP 子进程使用独立依赖环境，固定兼容 amap-mcp-server 的 Pydantic。
                server_command=["uvx", "--with", "pydantic<2.12", "amap-mcp-server"],
                env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
                auto_expand=True
            )
            self.amap_tool.expandable=True

            # ── 创建所有子Agent ──

            # 景点搜索
            print("  - 创建景点搜索Agent...")
            self.attraction_agent = SimpleAgent(
                name="景点搜索专家", llm=self.llm,
                system_prompt=ATTRACTION_AGENT_PROMPT)
            self.attraction_agent.add_tool(self.amap_tool)

            # 天气查询
            print("  - 创建天气查询Agent...")
            self.weather_agent = SimpleAgent(
                name="天气查询专家", llm=self.llm,
                system_prompt=WEATHER_AGENT_PROMPT)
            self.weather_agent.add_tool(self.amap_tool)

            # 酒店推荐
            print("  - 创建酒店推荐Agent...")
            self.hotel_agent = SimpleAgent(
                name="酒店推荐专家", llm=self.llm,
                system_prompt=HOTEL_AGENT_PROMPT)
            self.hotel_agent.add_tool(self.amap_tool)

            # 🆕 美食搜索
            print("  - 创建美食搜索Agent...")
            self.food_agent = SimpleAgent(
                name="美食搜索专家", llm=self.llm,
                system_prompt=FOOD_AGENT_PROMPT)
            self.food_agent.add_tool(self.amap_tool)

            # 🆕 预算评估（不需要MCP工具，纯LLM）
            print("  - 创建预算评估Agent...")
            self.budget_agent = SimpleAgent(
                name="预算评估专家", llm=self.llm,
                system_prompt=BUDGET_AGENT_PROMPT)

            # 行程规划（不需要工具）
            print("  - 创建行程规划Agent...")
            self.planner_agent = SimpleAgent(
                name="行程规划专家", llm=self.llm,
                system_prompt=PLANNER_AGENT_PROMPT)

            # ── 构建 Agent 注册表（Orchestrator 决策依据）──
            self.agent_registry: Dict[str, SubAgentInfo] = {
                "attraction": SubAgentInfo(
                    key="attraction", name="景点搜索专家", icon="📍",
                    description="搜索城市景点、地标、公园等",
                    trigger_keywords=["景点", "旅游", "游玩", "风景", "历史", "自然", "博物馆", "公园", "打卡"],
                    agent=self.attraction_agent),
                "weather": SubAgentInfo(
                    key="weather", name="天气查询专家", icon="🌤️",
                    description="查询城市天气预报",
                    trigger_keywords=["天气", "温度", "下雨", "晴天", "气候"],
                    agent=self.weather_agent),
                "hotel": SubAgentInfo(
                    key="hotel", name="酒店推荐专家", icon="🏨",
                    description="搜索酒店、住宿、民宿",
                    trigger_keywords=["酒店", "住宿", "旅馆", "民宿", "宾馆", "住"],
                    agent=self.hotel_agent),
                "food": SubAgentInfo(
                    key="food", name="美食搜索专家", icon="🍜",
                    description="搜索当地美食、餐厅、特色小吃",
                    trigger_keywords=["美食", "吃", "餐厅", "小吃", "特色菜", "火锅", "烧烤", "海鲜"],
                    agent=self.food_agent),
                "budget": SubAgentInfo(
                    key="budget", name="预算评估专家", icon="💰",
                    description="分析旅行费用、提供预算建议和省钱技巧",
                    trigger_keywords=["预算", "省钱", "便宜", "费用", "价格", "性价比", "穷游"],
                    depends_on=["attraction", "hotel"],
                    agent=self.budget_agent),
            }

            # ── 创建 Orchestrator Agent ──
            agent_list_text = "\n".join(
                f"- **{info.key}** ({info.icon} {info.name}): {info.description}"
                for info in self.agent_registry.values()
            )
            orchestrator_prompt = ORCHESTRATOR_PROMPT.format(agent_list=agent_list_text)

            print("  - 创建 Orchestrator 调度Agent...")
            self.orchestrator_agent = SimpleAgent(
                name="Orchestrator调度器",
                llm=self.llm,
                system_prompt=orchestrator_prompt
            )

            # 性能指标存储
            self.last_metrics: Optional[ExecutionMetrics] = None
            self.all_metrics: List[ExecutionMetrics] = []
            self.last_orchestration_plan: Optional[Dict] = None  # 最近一次调度决策

            print(f"✅ 多智能体系统初始化成功")
            print(f"   🧠 Orchestrator: 动态调度 {len(self.agent_registry)} 个可插拔Agent")
            for info in self.agent_registry.values():
                tools_count = len(info.agent.list_tools()) if info.agent else 0
                tool_suffix = f" ({tools_count}个工具)" if tools_count else ""
                print(f"     {info.icon} {info.name}{tool_suffix}")
            print(f"   ⚡ 执行模式: Orchestrator动态编排 + 并行执行")

        except Exception as e:
            print(f"❌ 多智能体系统初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    # ═══════════════════════════════════════════════════════════════
    # Orchestrator 调度逻辑
    # ═══════════════════════════════════════════════════════════════

    def _build_orchestrator_query(self, request: TripRequest) -> str:
        """构建 Orchestrator 输入：用户需求摘要"""
        parts = [
            f"目的地: {request.city}",
            f"日期: {request.start_date} ~ {request.end_date} ({request.travel_days}天)",
            f"交通偏好: {request.transportation}",
            f"住宿偏好: {request.accommodation}",
        ]
        if request.preferences:
            parts.append(f"旅行偏好: {', '.join(request.preferences)}")
        if request.free_text_input:
            parts.append(f"额外要求: {request.free_text_input}")
        parts.append("\n请根据以上信息，决定需要调度哪些Agent。直接输出JSON。")
        return "\n".join(parts)

    def _parse_orchestrator_response(self, response: str) -> dict:
        """解析 Orchestrator 返回的 JSON 调度计划"""
        try:
            # 尝试提取 JSON（可能被 markdown 包裹）
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            elif "{" in response:
                json_str = response[response.find("{"):response.rfind("}")+1]
            plan = json.loads(json_str.strip())
            return {
                "agents": plan.get("agents", ["attraction", "weather"]),
                "reasoning": plan.get("reasoning", ""),
                "special_focus": plan.get("special_focus", {})
            }
        except (json.JSONDecodeError, IndexError) as e:
            print(f"   ⚠️  Orchestrator 响应解析失败: {e}，使用默认调度")
            return {"agents": ["attraction", "weather", "hotel"],
                    "reasoning": "默认调度（解析失败回退）", "special_focus": {}}

    async def _orchestrate(self, request: TripRequest) -> dict:
        """
        Orchestrator 分析用户需求，返回调度计划。

        Returns:
            {"agents": ["attraction", "weather", ...], "reasoning": "...", "special_focus": {...}}
        """
        query = self._build_orchestrator_query(request)
        print("🧠 Orchestrator 正在分析用户需求...")
        response = await asyncio.to_thread(self.orchestrator_agent.run, query)
        plan = self._parse_orchestrator_response(response)

        # 过滤掉不存在的 agent
        valid_agents = [a for a in plan["agents"] if a in self.agent_registry]
        if len(valid_agents) < len(plan["agents"]):
            skipped = set(plan["agents"]) - set(valid_agents)
            print(f"   ⚠️  跳过未知Agent: {skipped}")
        plan["agents"] = valid_agents

        self.last_orchestration_plan = plan

        print(f"   📋 调度决策: {', '.join(valid_agents)}")
        print(f"   💭 理由: {plan['reasoning']}")
        if plan["special_focus"]:
            for agent_key, focus in plan["special_focus"].items():
                print(f"      🎯 {self.agent_registry[agent_key].name}: {focus}")

        return plan

    # ═══════════════════════════════════════════════════════════════
    # 新增子Agent执行方法
    # ═══════════════════════════════════════════════════════════════

    async def _run_food_agent(self, request: TripRequest) -> StepResult:
        """异步执行美食搜索Agent"""
        t0 = time.time()
        fallback = False
        try:
            print("🍜 [动态调度] 搜索美食...")
            keywords = "美食"
            if request.preferences and "美食" in request.preferences:
                keywords = "特色美食"
            query = f"请搜索{request.city}的{keywords}餐厅\n[TOOL_CALL:amap_maps_text_search:keywords={keywords},city={request.city},citylimit=true]"
            response = await asyncio.to_thread(self.food_agent.run, query)

            if self._llm_refused_tool(response):
                print("   ⚠️  美食Agent LLM未调用工具，回退到直接MCP调用...")
                fallback = True
                response = self._direct_mcp_call(
                    "amap_maps_text_search",
                    f"keywords={keywords},city={request.city},citylimit=true",
                    f"{request.city}美食搜索结果"
                )

            elapsed = time.time() - t0
            print(f"   ✅ 美食搜索完成 ({elapsed:.1f}s)")
            return StepResult(response=response, time=elapsed, fallback=fallback)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"   ❌ 美食搜索失败 ({elapsed:.1f}s): {e}")
            return StepResult(response="", time=elapsed, error=str(e), success=False)

    async def _run_budget_agent(self, request: TripRequest, context: str) -> StepResult:
        """异步执行预算评估Agent（依赖景点/酒店/美食数据）"""
        t0 = time.time()
        try:
            print("💰 [动态调度] 评估预算...")
            query = f"请根据以下信息评估{request.city}{request.travel_days}日游的预算：\n\n{context}"
            response = await asyncio.to_thread(self.budget_agent.run, query)
            elapsed = time.time() - t0
            print(f"   ✅ 预算评估完成 ({elapsed:.1f}s)")
            return StepResult(response=response, time=elapsed)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"   ❌ 预算评估失败 ({elapsed:.1f}s): {e}")
            return StepResult(response="", time=elapsed, error=str(e), success=False)

    async def plan_trip(self, request: TripRequest) -> TripPlan:
        """
        使用 Orchestrator 动态调度 + 多Agent并行协作生成旅行计划

        Args:
            request: 旅行请求

        Returns:
            旅行计划
        """
        metrics = ExecutionMetrics(
            city=request.city,
            travel_days=request.travel_days
        )
        total_start = time.time()
        context = self.harness.start_run(
            city=request.city,
            travel_days=request.travel_days,
            run_id=request.run_id,
            resume=request.resume,
        )
        self.last_run_context = context

        async def run_or_restore(agent_name: str, runner):
            if request.resume and agent_name in context.completed_agents:
                restored = self._restore_step_result(context, agent_name)
                if restored is not None:
                    self.harness.events.publish(
                        "agent_restored",
                        context.run_id,
                        agent_name=agent_name,
                    )
                    return restored
                raw_result = context.agent_results.get(agent_name)
                if agent_name == "planner" and isinstance(raw_result, str):
                    self.harness.events.publish(
                        "agent_restored",
                        context.run_id,
                        agent_name=agent_name,
                    )
                    return raw_result

            return await self.harness.run_agent(
                context,
                agent_name,
                runner,
            )

        try:
            print(f"\n{'='*60}")
            print(f"🚀 开始多智能体【并行】协作规划旅行...")
            print(f"目的地: {request.city}")
            print(f"日期: {request.start_date} 至 {request.end_date}")
            print(f"天数: {request.travel_days}天")
            print(f"偏好: {', '.join(request.preferences) if request.preferences else '无'}")
            print(f"{'='*60}\n")

            # ═══════════════════════════════════════════════════════
            # 阶段1: 并行执行三个独立Agent (景点 + 天气 + 酒店)
            # ═══════════════════════════════════════════════════════
            parallel_start = time.time()

            attraction_result, weather_result, hotel_result = await asyncio.gather(
                run_or_restore(
                    "attraction",
                    lambda: self._run_attraction_agent(request),
                ),
                run_or_restore(
                    "weather",
                    lambda: self._run_weather_agent(request),
                ),
                run_or_restore(
                    "hotel",
                    lambda: self._run_hotel_agent(request),
                ),
                return_exceptions=True
            )

            parallel_end = time.time()
            metrics.parallel_phase_time = parallel_end - parallel_start

            # 提取结果（容错：单个失败不影响整体）
            attraction_response = self._unwrap_step_result(
                attraction_result, "景点搜索", metrics, 'step1_attraction_time')
            weather_response = self._unwrap_step_result(
                weather_result, "天气查询", metrics, 'step2_weather_time')
            hotel_response = self._unwrap_step_result(
                hotel_result, "酒店推荐", metrics, 'step3_hotel_time')

            # 计算串行等价时间和加速比
            metrics.serial_equivalent = (
                metrics.step1_attraction_time +
                metrics.step2_weather_time +
                metrics.step3_hotel_time
            )
            metrics.speedup = (
                metrics.serial_equivalent / metrics.parallel_phase_time
                if metrics.parallel_phase_time > 0 else 1.0
            )

            # ═══════════════════════════════════════════════════════
            # 阶段2: 行程规划Agent (依赖阶段1的结果，必须串行)
            # ═══════════════════════════════════════════════════════
            print("📋 步骤4: 生成行程计划（整合前三步结果）...")
            planner_start = time.time()
            planner_query = self._build_planner_query(
                request, attraction_response, weather_response, hotel_response)
            planner_result = await run_or_restore(
                "planner",
                lambda: asyncio.to_thread(
                    self.planner_agent.run,
                    planner_query,
                ),
            )
            planner_response = (
                planner_result.response
                if isinstance(planner_result, StepResult)
                else str(planner_result)
            )
            metrics.step4_planner_time = time.time() - planner_start
            print(f"行程规划结果: {planner_response[:300]}...\n")

            # 解析最终计划
            trip_plan = self._parse_response(planner_response, request)
            evaluation = evaluate_trip_plan(request, trip_plan)
            self.harness.record_evaluation(context, evaluation)

            metrics.total_time = time.time() - total_start
            metrics.total_llm_calls = 4  # 3个工具Agent + 1个规划Agent
            metrics.success = True

            # ═══════════════════════════════════════════════════════
            # 性能报告
            # ═══════════════════════════════════════════════════════
            self._print_performance_report(metrics)

            self.last_metrics = metrics
            self.all_metrics.append(metrics)
            self.harness.finish_run(context, trip_plan)
            return trip_plan

        except Exception as e:
            metrics.total_time = time.time() - total_start
            metrics.success = False
            metrics.error_message = str(e)
            self.harness.fail_run(context, e)
            self.last_metrics = metrics
            self.all_metrics.append(metrics)

            print(f"❌ 生成旅行计划失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return self._create_fallback_plan(request)

    # ── Agent Key → 执行方法 映射表 ──
    def _get_agent_runner(self, key: str):
        """根据 agent key 返回对应的执行协程"""
        runners = {
            "attraction": self._run_attraction_agent,
            "weather": self._run_weather_agent,
            "hotel": self._run_hotel_agent,
            "food": self._run_food_agent,
        }
        return runners.get(key)

    async def plan_trip_stream(self, request: TripRequest):
        """
        Orchestrator 动态编排 + SSE 流式推送。

        流程:
        1. Orchestrator 分析用户需求 → 输出调度计划
        2. 按调度计划并行执行独立Agent
        3. 执行依赖Agent (如 budget 依赖 attraction+hotel)
        4. 行程规划Agent整合所有结果
        5. 流式推送完整过程

        Yields:
            dict: {"event": str, "data": dict}
        """
        metrics = ExecutionMetrics(city=request.city, travel_days=request.travel_days)
        total_start = time.time()
        harness_events: list[HarnessEvent] = []

        def collect_harness_event(event: HarnessEvent) -> None:
            harness_events.append(event)

        self.harness.events.subscribe(collect_harness_event)
        run_context = self.harness.start_run(
            city=request.city,
            travel_days=request.travel_days,
            run_id=request.run_id,
            resume=request.resume,
        )
        self.last_run_context = run_context

        def drain_harness_events() -> list[dict]:
            events = list(harness_events)
            harness_events.clear()
            return [
                {
                    "event": "harness",
                    "data": {
                        "event_type": event.event_type,
                        "run_id": event.run_id,
                        "sequence": event.sequence,
                        "timestamp": event.timestamp,
                        **event.data,
                    },
                }
                for event in events
            ]

        async def run_or_restore(agent_name: str, runner):
            """Reuse a completed checkpoint entry during a resumed stream."""
            if request.resume and agent_name in run_context.completed_agents:
                restored = self._restore_step_result(run_context, agent_name)
                if restored is not None:
                    self.harness.emit(
                        run_context,
                        "agent_restored",
                        agent_name=agent_name,
                    )
                    return restored
                raw_result = run_context.agent_results.get(agent_name)
                if agent_name == "planner" and isinstance(raw_result, str):
                    self.harness.emit(
                        run_context,
                        "agent_restored",
                        agent_name=agent_name,
                    )
                    return raw_result
            return await self.harness.run_agent(run_context, agent_name, runner)

        try:
            # ═══════════════════════════════════════════════════════
            # 阶段0: Orchestrator 分析 + 决策
            # ═══════════════════════════════════════════════════════
            yield {
                "event": "phase",
                "data": {"phase": "orchestration", "status": "running",
                         "message": "🧠 Orchestrator 正在分析您的需求..."}
            }

            orch_plan = await self._orchestrate(request)
            for event in drain_harness_events():
                yield event
            agents_to_dispatch = orch_plan["agents"]
            special_focus = orch_plan["special_focus"]

            # 通知前端调度决策
            dispatched_info = [
                {"key": k, "name": self.agent_registry[k].name, "icon": self.agent_registry[k].icon}
                for k in agents_to_dispatch
            ]
            yield {
                "event": "orchestration",
                "data": {
                    "agents": dispatched_info,
                    "reasoning": orch_plan["reasoning"],
                    "total": len(agents_to_dispatch)
                }
            }

            # ═══════════════════════════════════════════════════════
            # 阶段1: 并行执行所有独立Agent
            # ═══════════════════════════════════════════════════════
            independent_keys = [k for k in agents_to_dispatch
                                if not self.agent_registry[k].depends_on]

            if independent_keys:
                yield {
                    "event": "phase",
                    "data": {"phase": "parallel", "status": "running",
                             "message": f"⚡ 并行执行 {len(independent_keys)} 个Agent...",
                             "agents": [self.agent_registry[k].name for k in independent_keys]}
                }

                parallel_start = time.time()
                # 动态构建任务字典
                tasks = {}
                for key in independent_keys:
                    runner = self._get_agent_runner(key)
                    if runner:
                        task = asyncio.ensure_future(
                            run_or_restore(
                                key,
                                lambda runner=runner: runner(request),
                            )
                        )
                        tasks[task] = self.agent_registry[key].name

                # 广播所有 Agent 启动
                for agent_name in tasks.values():
                    yield {"event": "agent_start", "data": {"agent": agent_name}}

                # 等待 + 心跳
                step_results = {}
                pending_tasks = set(tasks.keys())
                while pending_tasks:
                    done, pending_tasks = await asyncio.wait(pending_tasks, timeout=2.0)
                    for coro in done:
                        agent_name = tasks[coro]
                        result = coro.result()
                        step_results[agent_name] = result
                        yield {
                            "event": "agent_done",
                            "data": {
                                "agent": agent_name,
                                "time": round(result.time, 1),
                                "status": "success" if result.success else "error",
                                "fallback": result.fallback,
                                "summary": (result.response[:100].replace('\n', ' ') + "...") if result.success else "",
                                "error": result.error if not result.success else None
                            }
                        }
                    for event in drain_harness_events():
                        yield event
                    if pending_tasks:
                        running_names = [tasks[p] for p in pending_tasks]
                        yield {
                            "event": "heartbeat",
                            "data": {"running": running_names,
                                     "done_count": len(tasks) - len(pending_tasks),
                                     "total": len(tasks)}
                        }

                metrics.parallel_phase_time = time.time() - parallel_start

                # 计算串行等价（近似）
                # Copy completed task durations into the named metrics fields.
                def step_time(agent_key: str) -> float:
                    info = self.agent_registry.get(agent_key)
                    result = step_results.get(info.name) if info else None
                    return result.time if isinstance(result, StepResult) else 0.0

                metrics.step1_attraction_time = step_time("attraction")
                metrics.step2_weather_time = step_time("weather")
                metrics.step3_hotel_time = step_time("hotel")

                all_times = [r.time for r in step_results.values() if r.time > 0]
                metrics.serial_equivalent = sum(all_times)
                metrics.speedup = (metrics.serial_equivalent / metrics.parallel_phase_time
                                   if metrics.parallel_phase_time > 0 else 1.0)
            else:
                step_results = {}

            # ═══════════════════════════════════════════════════════
            # 阶段2: 执行依赖Agent (budget等)
            # ═══════════════════════════════════════════════════════
            dependent_keys = [k for k in agents_to_dispatch
                              if self.agent_registry[k].depends_on]

            if dependent_keys:
                yield {
                    "event": "phase",
                    "data": {"phase": "dependent", "status": "running",
                             "message": "🔗 执行依赖Agent..."}
                }

                # 将前面所有结果拼成上下文
                context_parts = []
                for name, result in step_results.items():
                    if result.success:
                        context_parts.append(f"### {name}\n{result.response[:500]}")
                dependency_context = "\n\n".join(context_parts)

                for key in dependent_keys:
                    info = self.agent_registry[key]
                    yield {"event": "agent_start", "data": {"agent": info.name}}
                    t0 = time.time()

                    if key == "budget":
                        result = await run_or_restore(
                            key,
                            lambda: self._run_budget_agent(
                                request,
                                dependency_context,
                            ),
                        )
                    else:
                        result = StepResult(response="", time=0, success=False,
                                            error=f"未知依赖Agent: {key}")

                    result.time = time.time() - t0
                    step_results[info.name] = result
                    for event in drain_harness_events():
                        yield event
                    yield {
                        "event": "agent_done",
                        "data": {
                            "agent": info.name,
                            "time": round(result.time, 1),
                            "status": "success" if result.success else "error",
                            "fallback": result.fallback,
                            "summary": result.response[:100].replace('\n', ' ') + "..." if result.success else ""
                        }
                    }

            # ═══════════════════════════════════════════════════════
            # 阶段3: 行程规划Agent 整合所有结果
            # ═══════════════════════════════════════════════════════
            yield {
                "event": "phase",
                "data": {"phase": "planning", "status": "running",
                         "message": f"📋 正在整合信息生成 {request.travel_days} 天行程计划..."}
            }
            yield {"event": "agent_start", "data": {"agent": "行程规划专家"}}

            # 从 step_results 中提取各Agent结果
            def get_result(*names: str) -> str:
                for n in names:
                    if n in step_results and step_results[n].success:
                        return step_results[n].response
                return ""

            attraction_info = get_result("景点搜索专家")
            weather_info = get_result("天气查询专家")
            hotel_info = get_result("酒店推荐专家")
            food_info = get_result("美食搜索专家")
            budget_info = get_result("预算评估专家")

            planner_start = time.time()
            planner_query = self._build_planner_query(
                request, attraction_info, weather_info, hotel_info)

            # 有美食/预算结果时追加到 planner query
            if food_info:
                planner_query += f"\n\n**美食信息:**\n{food_info[:800]}"
            if budget_info:
                planner_query += f"\n\n**预算建议:**\n{budget_info[:500]}"

            # 注入 special_focus
            if special_focus:
                focus_lines = "\n".join(
                    f"- {self.agent_registry[k].name}: {v}"
                    for k, v in special_focus.items() if k in self.agent_registry)
                if focus_lines:
                    planner_query += f"\n\n**❗ Orchestrator 特别指示:**\n{focus_lines}"

            planner_result = await run_or_restore(
                "planner",
                lambda: asyncio.to_thread(
                    self.planner_agent.run,
                    planner_query,
                ),
            )
            for event in drain_harness_events():
                yield event
            metrics.step4_planner_time = time.time() - planner_start

            planner_response = (
                planner_result.response
                if isinstance(planner_result, StepResult)
                else str(planner_result)
            )

            yield {
                "event": "agent_done",
                "data": {"agent": "行程规划专家",
                         "time": round(metrics.step4_planner_time, 1),
                         "status": "success", "fallback": False}
            }

            # 解析最终计划
            trip_plan = self._parse_response(planner_response, request)
            evaluation = evaluate_trip_plan(request, trip_plan)
            self.harness.record_evaluation(run_context, evaluation)

            metrics.total_time = time.time() - total_start
            metrics.total_llm_calls = len(agents_to_dispatch) + 1  # N个子Agent + 1个planner
            metrics.success = True

            self.last_metrics = metrics
            self.all_metrics.append(metrics)
            self._print_performance_report(metrics)
            self.harness.finish_run(run_context, trip_plan)
            for event in drain_harness_events():
                yield event

            # 完成
            yield {"event": "complete", "data": trip_plan.model_dump()}
            yield {
                "event": "metrics",
                "data": {
                    "step1_attraction_time": round(metrics.step1_attraction_time, 1),
                    "step2_weather_time": round(metrics.step2_weather_time, 1),
                    "step3_hotel_time": round(metrics.step3_hotel_time, 1),
                    "parallel_phase_time": round(metrics.parallel_phase_time, 1),
                    "serial_equivalent": round(metrics.serial_equivalent, 1),
                    "speedup": round(metrics.speedup, 2),
                    "step4_planner_time": round(metrics.step4_planner_time, 1),
                    "total_time": round(metrics.total_time, 1),
                    "agents_dispatched": len(agents_to_dispatch),
                }
            }

        except Exception as e:
            metrics.total_time = time.time() - total_start
            metrics.success = False
            metrics.error_message = str(e)
            self.last_metrics = metrics
            self.all_metrics.append(metrics)
            self.harness.fail_run(run_context, e)
            for event in drain_harness_events():
                yield event

            yield {
                "event": "error",
                "data": {"message": f"旅行规划失败: {str(e)}", "fallback": True}
            }
            try:
                fallback = self._create_fallback_plan(request)
                yield {"event": "complete", "data": fallback.model_dump()}
            except:
                pass

        finally:
            self.harness.events.unsubscribe(collect_harness_event)

    # ═══════════════════════════════════════════════════════════════
    # 并行任务协程 (每个Agent在线程池中独立运行)
    # ═══════════════════════════════════════════════════════════════

    async def _run_attraction_agent(self, request: TripRequest) -> StepResult:
        """异步执行景点搜索Agent（LLM优先 + 直接MCP回退）"""
        t0 = time.time()
        fallback = False
        try:
            print("📍 [并行] 步骤1: 搜索景点...")
            # 使用统一的关键词构建（偏好 + 额外需求中的具体地点）
            keywords = request.preferences[0] if request.preferences else "景点"
            extra_places = self._extract_places(request.free_text_input) if request.free_text_input else []
            if extra_places:
                keywords = keywords + "、" + "、".join(extra_places)
                print(f"   🔍 检测到额外需求中的地点: {extra_places}")
            query = f"请使用amap_maps_text_search工具搜索{request.city}的{keywords}相关景点。\n[TOOL_CALL:amap_maps_text_search:keywords={keywords},city={request.city},citylimit=true]"
            response = await asyncio.to_thread(self.attraction_agent.run, query)

            if self._llm_refused_tool(response):
                print("   ⚠️  景点Agent LLM未调用工具，回退到直接MCP调用...")
                fallback = True
                response = self._direct_mcp_call(
                    "amap_maps_text_search",
                    f"keywords={keywords},city={request.city},citylimit=true",
                    f"{request.city}景点搜索结果"
                )

            elapsed = time.time() - t0
            print(f"   ✅ 景点搜索完成 ({elapsed:.1f}s): {response[:150]}...")
            return StepResult(response=response, time=elapsed, fallback=fallback)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"   ❌ 景点搜索失败 ({elapsed:.1f}s): {e}")
            return StepResult(response="", time=elapsed, error=str(e), success=False)

    async def _run_weather_agent(self, request: TripRequest) -> StepResult:
        """异步执行天气查询Agent（LLM优先 + 直接MCP回退）"""
        t0 = time.time()
        fallback = False
        try:
            print("🌤️  [并行] 步骤2: 查询天气...")
            query = f"请查询{request.city}的天气信息\n[TOOL_CALL:amap_maps_weather:city={request.city}]"
            # Weather is a deterministic data lookup. Call the already
            # connected MCP tool first instead of relying on the LLM to emit
            # the exact tool/action format.
            response = await asyncio.to_thread(
                self._direct_mcp_call,
                "amap_maps_weather",
                f"city={request.city}",
                f"{request.city}天气预报",
            )
            fallback = True

            if response.startswith("直接调用 amap_maps_weather 失败:"):
                print("   ⚠️  直接天气 MCP 调用失败，回退到天气 Agent...")
                fallback = False
                response = await asyncio.to_thread(self.weather_agent.run, query)

            elapsed = time.time() - t0
            print(f"   ✅ 天气查询完成 ({elapsed:.1f}s): {response[:150]}...")
            return StepResult(response=response, time=elapsed, fallback=fallback)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"   ❌ 天气查询失败 ({elapsed:.1f}s): {e}")
            return StepResult(response="", time=elapsed, error=str(e), success=False)

    async def _run_hotel_agent(self, request: TripRequest) -> StepResult:
        """异步执行酒店推荐Agent（LLM优先 + 直接MCP回退）"""
        t0 = time.time()
        fallback = False
        try:
            print("🏨 [并行] 步骤3: 搜索酒店...")
            query = f"请搜索{request.city}的{request.accommodation}酒店\n[TOOL_CALL:amap_maps_text_search:keywords={request.accommodation},city={request.city},citylimit=true]"
            response = await asyncio.to_thread(self.hotel_agent.run, query)

            if self._llm_refused_tool(response):
                print("   ⚠️  酒店Agent LLM未调用工具，回退到直接MCP调用...")
                fallback = True
                response = self._direct_mcp_call(
                    "amap_maps_text_search",
                    f"keywords={request.accommodation},city={request.city},citylimit=true",
                    f"{request.city}酒店搜索结果"
                )

            elapsed = time.time() - t0
            print(f"   ✅ 酒店搜索完成 ({elapsed:.1f}s): {response[:150]}...")
            return StepResult(response=response, time=elapsed, fallback=fallback)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"   ❌ 酒店搜索失败 ({elapsed:.1f}s): {e}")
            return StepResult(response="", time=elapsed, error=str(e), success=False)

    def _llm_refused_tool(self, response: str) -> bool:
        """
        检测 LLM 是否拒绝了工具调用。

        判断逻辑：
        1. 响应太短（< 300字符）→ 不太可能包含工具查询结果
        2. 包含拒绝关键词（"没有可用"、"无法获取"等）
        3. 不包含工具调用标记或工具结果

        工具返回的数据通常 > 500 字符，所以短响应 + 拒绝关键词 = 真拒绝。
        """
        # 长响应通常表示工具已经被调用了（数据量大）
        if len(response) > 500:
            return False

        refuse_keywords = [
            "没有可用的", "无法获取", "无法访问", "暂不支持",
            "建议您通过", "我无法", "系统中没有"
        ]
        has_tool_marker = "[TOOL_CALL:" in response or "工具调用结果" in response or "根据" in response
        has_refuse = any(kw in response for kw in refuse_keywords)

        return has_refuse and not has_tool_marker

    def _direct_mcp_call(self, tool_name: str, params: str, label: str) -> str:
        """直接调用 MCP 工具，绕过 LLM"""
        try:
            self.harness.tool_policy.check(tool_name)
            # ToolRegistry.execute_tool wraps the string as {"input": ...},
            # which is not a valid argument object for amap-mcp-server.
            # Call the MCP server with its real tool name and typed arguments.
            arguments = {}
            for pair in params.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    value = value.strip()
                    if value.lower() in ("true", "false"):
                        value = value.lower() == "true"
                    arguments[key.strip()] = value

            mcp_tool_name = tool_name.removeprefix("amap_")
            key = f"amap:{mcp_tool_name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"
            raw = self.resilience.call(
                key,
                lambda: self.amap_tool.run({
                    "action": "call_tool",
                    "tool_name": mcp_tool_name,
                    "arguments": arguments,
                }),
            )
            return f"根据{label}，以下是返回结果：\n\n{raw}"
        except Exception as e:
            return f"直接调用 {tool_name} 失败: {e}"

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    def _restore_step_result(
        self,
        context,
        agent_name: str,
    ) -> Optional[StepResult]:
        """Rebuild a StepResult saved in a JSON checkpoint."""
        raw = context.agent_results.get(agent_name)
        if not isinstance(raw, dict):
            return None

        return StepResult(
            response=str(raw.get("response", "")),
            time=float(raw.get("time", 0.0)),
            error=raw.get("error"),
            success=bool(raw.get("success", True)),
            fallback=bool(raw.get("fallback", False)),
        )

    def _unwrap_step_result(
        self, result, step_name: str,
        metrics: ExecutionMetrics, time_attr: str
    ) -> str:
        """解包步骤结果，处理异常和计时"""
        if isinstance(result, Exception):
            print(f"   ⚠️  {step_name} Agent 抛出异常: {result}")
            return ""
        if isinstance(result, StepResult):
            setattr(metrics, time_attr, result.time)
            if not result.success:
                print(f"   ⚠️  {step_name} 失败: {result.error}")
                return ""
            return result.response
        # 兼容非StepResult的返回值
        return str(result) if result else ""

    def _print_performance_report(self, m: ExecutionMetrics):
        """打印格式化的性能报告"""
        print(f"\n{'='*60}")
        print(f"📊 性能指标报告")
        print(f"{'='*60}")
        print(f"  目的地: {m.city} | 天数: {m.travel_days}天")
        print(f"{'─'*40}")
        print(f"  ⚡ 并行阶段 (步骤1-3):")
        print(f"     📍 景点搜索:    {m.step1_attraction_time:>6.1f}s")
        print(f"     🌤️  天气查询:    {m.step2_weather_time:>6.1f}s")
        print(f"     🏨 酒店搜索:    {m.step3_hotel_time:>6.1f}s")
        print(f"     ─────────────────────────")
        print(f"     🔴 串行等价耗时: {m.serial_equivalent:>6.1f}s  (step1+step2+step3)")
        print(f"     🟢 并行实际耗时: {m.parallel_phase_time:>6.1f}s  (max(step1,step2,step3))")
        print(f"     🚀 加速比:       {m.speedup:>6.2f}x  (节省 {(1 - 1/m.speedup)*100:.0f}%)" if m.speedup > 1 else "")
        print(f"  📋 串行阶段 (步骤4):")
        print(f"     📝 行程规划:    {m.step4_planner_time:>6.1f}s")
        print(f"{'─'*40}")
        print(f"  ⏱️  总耗时:        {m.total_time:>6.1f}s")
        print(f"  🔢 LLM调用次数:   {m.total_llm_calls}")
        print(f"{'='*60}\n")
    
    def _build_attraction_query(self, request: TripRequest) -> str:
        """构建景点搜索查询 — 融合偏好 + 额外需求中的具体地点"""
        # 收集搜索关键词
        keywords_parts = []

        # 1. 偏好标签
        if request.preferences:
            keywords_parts.append(request.preferences[0])

        # 2. 从额外需求中提取具体地点名（如 "我想去东方明珠" → "东方明珠"）
        if request.free_text_input:
            extra_places = self._extract_places(request.free_text_input)
            if extra_places:
                keywords_parts.extend(extra_places)

        keywords = "、".join(keywords_parts) if keywords_parts else "景点"

        # 直接返回工具调用格式
        query = f"请使用amap_maps_text_search工具搜索{request.city}的{keywords}相关景点。\n[TOOL_CALL:amap_maps_text_search:keywords={keywords},city={request.city}]"
        return query

    def _extract_places(self, text: str) -> list:
        """
        从自由文本中提取具体地点名称。

        简单规则：匹配"我想去XXX"、"必须去XXX"、"一定要去XXX" 等模式
        """
        import re
        places = []
        # 匹配"想去/必须去/一定要去/要去 XXX"
        patterns = [
            r'(?:想去|必须去|一定要去|要去|必去|打卡)\s*[：:]?\s*([^\s，。,\.\n]+)',
            r'包含\s*[：:]?\s*([^\s，。,\.\n]+)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            places.extend(matches)
        return places

    def _build_planner_query(self, request: TripRequest, attractions: str, weather: str, hotels: str = "") -> str:
        """构建行程规划查询 — 额外需求放在最前面确保不丢失"""
        # 如果用户有额外需求，放在最显眼的位置
        extra_section = ""
        if request.free_text_input:
            extra_section = f"""
**❗❗ 用户特别要求（必须满足，优先级最高）:**
{request.free_text_input}
请务必将这些要求体现在行程中，如果涉及具体地点或活动，必须在景点列表中包含。
"""

        query = f"""请根据以下信息生成{request.city}的{request.travel_days}天旅行计划:

{extra_section}
**基本信息:**
- 城市: {request.city}
- 日期: {request.start_date} 至 {request.end_date}
- 天数: {request.travel_days}天
- 交通方式: {request.transportation}
- 住宿: {request.accommodation}
- 偏好: {', '.join(request.preferences) if request.preferences else '无'}

**景点信息:**
{attractions}

**天气信息:**
{weather}

**酒店信息:**
{hotels}

**要求:**
1. 每天安排2-3个景点
2. 每天必须包含早中晚三餐
3. 每天推荐一个具体的酒店(从酒店信息中选择)
4. 考虑景点之间的距离和交通方式
5. 返回完整的JSON格式数据
6. 景点的经纬度坐标要真实准确
"""

        return query
    
    def _parse_response(self, response: str, request: TripRequest) -> TripPlan:
        """
        解析Agent响应
        
        Args:
            response: Agent响应文本
            request: 原始请求
            
        Returns:
            旅行计划
        """
        try:
            # 尝试从响应中提取JSON
            # 查找JSON代码块
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "{" in response and "}" in response:
                # 直接查找JSON对象
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                json_str = response[json_start:json_end]
            else:
                raise ValueError("响应中未找到JSON数据")
            
            # 解析JSON
            # 二次校验：即使 JSON 可解析，也必须符合 TripPlan 契约。
            data = validate_model_response(response, TripPlan).model_dump()
            
            # 转换为TripPlan对象
            trip_plan = TripPlan(**data)
            
            return trip_plan
            
        except Exception as e:
            print(f"⚠️  解析响应失败: {str(e)}")
            print(f"   将使用备用方案生成计划")
            return self._create_fallback_plan(request)
    
    def _create_fallback_plan(self, request: TripRequest) -> TripPlan:
        """创建备用计划(当Agent失败时)"""
        from datetime import datetime, timedelta
        
        # 解析日期
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
        
        # 创建每日行程
        days = []
        for i in range(request.travel_days):
            current_date = start_date + timedelta(days=i)
            
            day_plan = DayPlan(
                date=current_date.strftime("%Y-%m-%d"),
                day_index=i,
                description=f"第{i+1}天行程",
                transportation=request.transportation,
                accommodation=request.accommodation,
                attractions=[
                    Attraction(
                        name=f"{request.city}景点{j+1}",
                        address=f"{request.city}市",
                        location=Location(longitude=116.4 + i*0.01 + j*0.005, latitude=39.9 + i*0.01 + j*0.005),
                        visit_duration=120,
                        description=f"这是{request.city}的著名景点",
                        category="景点"
                    )
                    for j in range(2)
                ],
                meals=[
                    Meal(type="breakfast", name=f"第{i+1}天早餐", description="当地特色早餐"),
                    Meal(type="lunch", name=f"第{i+1}天午餐", description="午餐推荐"),
                    Meal(type="dinner", name=f"第{i+1}天晚餐", description="晚餐推荐")
                ]
            )
            days.append(day_plan)
        
        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=[],
            overall_suggestions=f"这是为您规划的{request.city}{request.travel_days}日游行程,建议提前查看各景点的开放时间。"
        )


    # ═══════════════════════════════════════════════════════════════
    # NLP 自然语言解析
    # ═══════════════════════════════════════════════════════════════

    async def parse_natural_language(self, text: str) -> dict:
        """
        用 LLM 从自然语言中提取结构化旅行参数。

        示例输入: "7月10-12日去北京，喜欢美食和历史文化，想去故宫"
        输出: {city, start_date, end_date, preferences, ...}
        """
        today = time.strftime("%Y-%m-%d")
        prompt = f"""你是一个旅行意图解析器。从用户输入中提取结构化信息。

当前日期: {today}

用户输入: "{text}"

请以纯JSON格式返回（不要markdown包裹）:
{{
  "city": "城市名",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "travel_days": 数字,
  "transportation": "公共交通/自驾/步行/混合",
  "accommodation": "经济型酒店/舒适型酒店/豪华酒店/民宿",
  "preferences": ["偏好1", "偏好2"],
  "free_text_input": "未被归类的额外要求"
}}

**解析规则:**
1. 城市名必须提取（如"北京"、"上海"）
2. 日期尽量智能推断：如果只说"下周五到周日"就推算具体日期；如果只说"3天"或没提日期就用当前日期起算
3. 交通默认为"公共交通"，除非用户提到自驾/租车/打车
4. 住宿默认为"经济型酒店"，除非用户指定
5. preferences 从 [历史文化, 自然风光, 美食, 购物, 艺术, 休闲] 中匹配
6. 无法归类的具体需求（如"想去故宫"、"对海鲜过敏"）放入 free_text_input
7. 如果信息不完整，用合理默认值填充并标注

直接输出JSON，不要解释:"""

        response = await asyncio.to_thread(self.llm.invoke,
            [{"role": "user", "content": prompt}])

        # 解析 JSON
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            if "{" in json_str:
                json_str = json_str[json_str.find("{"):json_str.rfind("}")+1]
            # Pydantic 校验让解析结果与 TripIntent 契约保持一致。
            return validate_model_response(response, TripIntent).model_dump()
        except Exception:
            # 回退：尝试从文本中提取城市名
            city = text.replace("去", " ").replace("到", " ").split()[0] if text else "北京"
            return {
                "city": city, "start_date": today,
                "end_date": today, "travel_days": 1,
                "transportation": "公共交通", "accommodation": "经济型酒店",
                "preferences": [], "free_text_input": text
            }


# 全局多智能体系统实例
_multi_agent_planner = None


def get_trip_planner_agent() -> MultiAgentTripPlanner:
    """获取多智能体旅行规划系统实例(单例模式)"""
    global _multi_agent_planner

    if _multi_agent_planner is None:
        _multi_agent_planner = MultiAgentTripPlanner()

    return _multi_agent_planner

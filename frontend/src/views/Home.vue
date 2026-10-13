<template>
  <div class="home-container">
    <!-- 背景装饰 -->
    <div class="bg-decoration">
      <div class="circle circle-1"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-3"></div>
    </div>

    <!-- 页面标题 -->
    <div class="page-header">
      <div class="icon-wrapper">
        <span class="icon">✈️</span>
      </div>
      <h1 class="page-title">智能旅行助手</h1>
      <p class="page-subtitle">基于AI的个性化旅行规划,让每一次出行都完美无忧</p>
    </div>

    <a-card class="form-card" :bordered="false">
      <!-- 输入模式切换 -->
      <div class="mode-switch">
        <a-radio-group v-model:value="inputMode" button-style="solid" size="large">
          <a-radio-button value="free">🗣️ 自由输入</a-radio-button>
          <a-radio-button value="form">📋 表单填写</a-radio-button>
        </a-radio-group>
      </div>

      <a-form
        :model="formData"
        layout="vertical"
        @finish="handleSubmit"
      >
        <!-- 自由输入模式 -->
        <div v-if="inputMode === 'free'" class="free-input-section">
          <div class="free-input-label">
            💬 用一句话描述你的旅行计划，AI 会自动解析
          </div>
          <a-textarea
            v-model:value="freeText"
            placeholder="例如：7月10-12日去北京，喜欢美食和历史文化，想去故宫和长城，住经济酒店"
            :rows="3"
            size="large"
            class="free-textarea"
            :disabled="loading"
          />
          <a-button
            type="primary"
            size="large"
            :loading="parsing"
            @click="handleParse"
            class="parse-button"
          >
            🧠 智能解析
          </a-button>
        </div>

        <!-- 第一步:目的地和日期 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">📍</span>
            <span class="section-title">目的地与日期</span>
          </div>

          <a-row :gutter="24">
            <a-col :span="8">
              <a-form-item name="city" :rules="[{ required: true, message: '请输入目的地城市' }]">
                <template #label>
                  <span class="form-label">目的地城市</span>
                </template>
                <a-input
                  v-model:value="formData.city"
                  placeholder="例如: 北京"
                  size="large"
                  class="custom-input"
                >
                  <template #prefix>
                    <span style="color: #1890ff;">🏙️</span>
                  </template>
                </a-input>
              </a-form-item>
            </a-col>
            <a-col :span="6">
              <a-form-item name="start_date" :rules="[{ required: true, message: '请选择开始日期' }]">
                <template #label>
                  <span class="form-label">开始日期</span>
                </template>
                <a-date-picker
                  v-model:value="formData.start_date"
                  style="width: 100%"
                  size="large"
                  class="custom-input"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :span="6">
              <a-form-item name="end_date" :rules="[{ required: true, message: '请选择结束日期' }]">
                <template #label>
                  <span class="form-label">结束日期</span>
                </template>
                <a-date-picker
                  v-model:value="formData.end_date"
                  style="width: 100%"
                  size="large"
                  class="custom-input"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :span="4">
              <a-form-item>
                <template #label>
                  <span class="form-label">旅行天数</span>
                </template>
                <div class="days-display-compact">
                  <span class="days-value">{{ formData.travel_days }}</span>
                  <span class="days-unit">天</span>
                </div>
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <!-- 第二步:偏好设置 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">⚙️</span>
            <span class="section-title">偏好设置</span>
          </div>

          <a-row :gutter="24">
            <a-col :span="8">
              <a-form-item name="transportation">
                <template #label>
                  <span class="form-label">交通方式</span>
                </template>
                <a-select v-model:value="formData.transportation" size="large" class="custom-select">
                  <a-select-option value="公共交通">🚇 公共交通</a-select-option>
                  <a-select-option value="自驾">🚗 自驾</a-select-option>
                  <a-select-option value="步行">🚶 步行</a-select-option>
                  <a-select-option value="混合">🔀 混合</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item name="accommodation">
                <template #label>
                  <span class="form-label">住宿偏好</span>
                </template>
                <a-select v-model:value="formData.accommodation" size="large" class="custom-select">
                  <a-select-option value="经济型酒店">💰 经济型酒店</a-select-option>
                  <a-select-option value="舒适型酒店">🏨 舒适型酒店</a-select-option>
                  <a-select-option value="豪华酒店">⭐ 豪华酒店</a-select-option>
                  <a-select-option value="民宿">🏡 民宿</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item name="preferences">
                <template #label>
                  <span class="form-label">旅行偏好</span>
                </template>
                <div class="preference-tags">
                  <a-checkbox-group v-model:value="formData.preferences" class="custom-checkbox-group">
                    <a-checkbox value="历史文化" class="preference-tag">🏛️ 历史文化</a-checkbox>
                    <a-checkbox value="自然风光" class="preference-tag">🏞️ 自然风光</a-checkbox>
                    <a-checkbox value="美食" class="preference-tag">🍜 美食</a-checkbox>
                    <a-checkbox value="购物" class="preference-tag">🛍️ 购物</a-checkbox>
                    <a-checkbox value="艺术" class="preference-tag">🎨 艺术</a-checkbox>
                    <a-checkbox value="休闲" class="preference-tag">☕ 休闲</a-checkbox>
                  </a-checkbox-group>
                </div>
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <!-- 第三步:额外要求 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">💬</span>
            <span class="section-title">额外要求</span>
          </div>

          <a-form-item name="free_text_input">
            <a-textarea
              v-model:value="formData.free_text_input"
              placeholder="请输入您的额外要求,例如:想去看升旗、需要无障碍设施、对海鲜过敏等..."
              :rows="3"
              size="large"
              class="custom-textarea"
            />
          </a-form-item>
        </div>

        <!-- 提交按钮 -->
        <a-form-item>
          <a-button
            type="primary"
            html-type="submit"
            :loading="loading"
            size="large"
            block
            class="submit-button"
          >
            <template v-if="!loading">
              <span class="button-icon">🚀</span>
              <span>开始规划我的旅行</span>
            </template>
            <template v-else>
              <span>正在生成中...</span>
            </template>
          </a-button>
        </a-form-item>

        <!-- 实时 Agent 执行状态 -->
        <a-form-item v-if="loading">
          <div class="loading-container">
            <!-- 进度条 -->
            <a-progress
              :percent="loadingProgress"
              status="active"
              :stroke-color="{
                '0%': '#667eea',
                '100%': '#764ba2',
              }"
              :stroke-width="10"
            />

            <!-- 当前状态 -->
            <p class="loading-status">{{ loadingStatus }}</p>
            <div v-if="currentHarnessPhase" class="harness-current-phase">
              当前 Harness 阶段：<strong>{{ currentHarnessPhase }}</strong>
            </div>

            <!-- Orchestrator 调度决策面板 -->
            <div v-if="orchestration" class="orchestration-panel">
              <div class="orch-header">
                🧠 Orchestrator 调度决策
                <span class="orch-count">调度 {{ orchestration.total }} 个Agent</span>
              </div>
              <div class="orch-reasoning">💭 {{ orchestration.reasoning }}</div>
              <div class="orch-agents">
                <span
                  v-for="a in orchestration.agents"
                  :key="a.key"
                  class="orch-agent-tag"
                >{{ a.icon }} {{ a.name }}</span>
              </div>
            </div>

            <!-- Agent 实时状态卡片 (动态数量) -->
            <div class="agent-status-grid">
              <div
                v-for="agent in agents"
                :key="agent.name"
                class="agent-status-card"
                :class="`agent-${agent.status}`"
              >
                <div class="agent-icon">{{ agent.icon }}</div>
                <div class="agent-info">
                  <div class="agent-name">{{ agent.name }}</div>
                  <div class="agent-state">
                    <template v-if="agent.status === 'idle'">
                      <span class="state-dot idle"></span> 等待中
                    </template>
                    <template v-else-if="agent.status === 'running'">
                      <span class="state-dot running"></span> 执行中...
                    </template>
                    <template v-else-if="agent.status === 'done'">
                      <span class="state-dot done"></span> 完成
                      <span class="agent-time">{{ agent.time }}s</span>
                    </template>
                    <template v-else-if="agent.status === 'fallback'">
                      <span class="state-dot fallback"></span> 直接 MCP
                      <span class="agent-time">{{ agent.time }}s</span>
                    </template>
                    <template v-else-if="agent.status === 'error'">
                      <span class="state-dot error"></span> 失败
                    </template>
                  </div>
                  <span v-if="agent.attempts > 0" class="agent-attempts">
                    第 {{ agent.attempts }} 次
                  </span>
                  <div v-if="agent.error" class="agent-error-message">{{ agent.error }}</div>
                  <div v-if="agent.summary" class="agent-summary">
                    {{ agent.summary }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 性能指标 -->
            <div v-if="metrics" class="metrics-badge">
              ⚡ 并行加速比: <strong>{{ metrics.speedup }}x</strong>
              &nbsp;|&nbsp;
              ⏱️ 总耗时: <strong>{{ metrics.total_time }}s</strong>
            </div>

            <!-- Harness 运行时事件 -->
            <div v-if="harnessEvents.length" class="harness-panel">
              <div class="harness-title">🛡️ Harness 运行时</div>
              <div v-for="(item, index) in harnessEvents" :key="`${item.event_type}-${index}`" class="harness-event">
                <span class="harness-event-type">{{ item.event_type }}</span>
                <span>{{ formatHarnessEvent(item) }}</span>
              </div>
            </div>
          </div>
        </a-form-item>
      </a-form>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { generateTripPlanStream, parseNaturalLanguage } from '@/services/api'
import type { SSEEvent } from '@/services/api'
import type { TripFormData } from '@/types'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'

const router = useRouter()
const loading = ref(false)
const loadingProgress = ref(0)
const loadingStatus = ref('')

// 输入模式切换
const inputMode = ref<'form' | 'free'>('free')  // 默认自由输入
const freeText = ref('')
const parsing = ref(false)  // NLP 解析中

// 每个 Agent 的实时状态
interface AgentStatus {
  name: string
  icon: string
  status: 'idle' | 'running' | 'done' | 'fallback' | 'error'
  time: number | null
  summary: string
  attempts?: number
  error?: string
}
const agents = ref<AgentStatus[]>([
  { name: '行程规划专家', icon: '📋', status: 'idle', time: null, summary: '' },
])
// Orchestrator 调度信息
const orchestration = ref<{ agents: any[], reasoning: string, total: number } | null>(null)

// 性能指标
const metrics = ref<{ speedup: number; total_time: number } | null>(null)
const harnessEvents = ref<Array<{ event_type: string; sequence?: number; data: any }>>([])
const currentHarnessPhase = ref('')

const formData = reactive<TripFormData & { start_date: Dayjs | null; end_date: Dayjs | null }>({
  city: '',
  start_date: null,
  end_date: null,
  travel_days: 1,
  transportation: '公共交通',
  accommodation: '经济型酒店',
  preferences: [],
  free_text_input: ''
})

// 监听日期变化,自动计算旅行天数
watch([() => formData.start_date, () => formData.end_date], ([start, end]) => {
  if (start && end) {
    const days = end.diff(start, 'day') + 1
    if (days > 0 && days <= 30) {
      formData.travel_days = days
    } else if (days > 30) {
      message.warning('旅行天数不能超过30天')
      formData.end_date = null
    } else {
      message.warning('结束日期不能早于开始日期')
      formData.end_date = null
    }
  }
})

// 重置 Agent 状态
const resetAgents = () => {
  agents.value = [{ name: '行程规划专家', icon: '📋', status: 'idle', time: null, summary: '' }]
  orchestration.value = null
  metrics.value = null
  harnessEvents.value = []
  currentHarnessPhase.value = ''
}

const formatHarnessEvent = (item: { event_type: string; data: any }) => {
  const data = item.data || {}
  if (item.event_type === 'agent_retry') {
    return `${data.agent_name || 'Agent'} 第 ${data.attempt} 次尝试：${data.reason || ''}`
  }
  if (item.event_type === 'evaluation_finished') {
    return `评测分数 ${data.score ?? '-'}，结果：${data.passed ? '通过' : '未完全通过'}`
  }
  if (data.agent_name) return `Agent: ${data.agent_name}`
  if (data.error) return `错误：${data.error}`
  return '运行事件已记录'
}

// 根据后端事件更新 Agent 状态
const agentAliases: Record<string, string> = {
  attraction: '景点搜索专家',
  weather: '天气查询专家',
  hotel: '酒店推荐专家',
  food: '美食搜索专家',
  budget: '预算评估专家',
  planner: '行程规划专家',
}

const findAgent = (agentName: string) => agents.value.find(
  agent => agent.name === agentName || agent.name === agentAliases[agentName]
)

const handleSSEEvent = (evt: SSEEvent) => {
  const { event, data } = evt

  switch (event) {
    case 'phase':
      currentHarnessPhase.value = data.phase || ''
      loadingStatus.value = data.message || `阶段: ${data.phase}`
      if (data.phase === 'planning') {
        loadingProgress.value = 70
      }
      break

    case 'orchestration':
      // Orchestrator 调度决策 → 动态构建 Agent 列表
      orchestration.value = data
      if (data.agents) {
        const plannerAgent = { name: '行程规划专家', icon: '📋', status: 'idle' as const, time: null, summary: '' }
        const dispatchedAgents = data.agents.map((a: any) => ({
          name: a.name, icon: a.icon, status: 'idle' as const, time: null, summary: ''
        }))
        agents.value = [...dispatchedAgents, plannerAgent]
      }
      loadingStatus.value = `🧠 Orchestrator 决策: 调度 ${data.total} 个Agent — ${data.reasoning}`
      loadingProgress.value = 10
      break

    case 'agent_start':
      loadingStatus.value = `${data.agent} 正在执行...`
      // 找到对应Agent并标记为 running
      const started = findAgent(data.agent)
      if (started) started.status = 'running'
      break

    case 'agent_done':
      const done = findAgent(data.agent)
      if (done) {
        if (data.fallback && data.status === 'success') {
          done.status = 'fallback'  // 回退模式成功 → 橙色提示
        } else {
          done.status = data.status === 'success' ? 'done' : 'error'
        }
        done.time = data.time
        done.summary = data.summary || ''
        done.error = data.error || ''
      }
      // 更新进度（fallback 也算成功）
      const doneCount = agents.value.filter(a => a.status === 'done' || a.status === 'fallback').length
      loadingProgress.value = Math.min(15 + doneCount * 20, 90)
      loadingStatus.value = data.fallback
        ? `${data.agent} 完成 (直接 MCP, ${data.time}s)`
        : `${data.agent} 完成 (${data.time}s)`
      break

    case 'heartbeat':
      // 心跳事件：更新还在运行的 Agent 的等待时间
      if (data.running) {
        loadingStatus.value = `正在等待: ${data.running.join('、')} (已完成 ${data.done_count}/${data.total})`
      }
      break

    case 'metrics':
      metrics.value = {
        speedup: data.speedup,
        total_time: data.total_time
      }
      loadingProgress.value = 100
      loadingStatus.value = '✅ 完成!'
      break

    case 'harness':
      currentHarnessPhase.value = data.event_type || currentHarnessPhase.value
      if (data.event_type === 'agent_attempt_started') {
        const agent = findAgent(data.agent_name)
        if (agent) {
          agent.status = 'running'
          agent.attempts = data.attempt || agent.attempts || 0
          agent.error = ''
        }
      } else if (data.event_type === 'agent_retry') {
        const agent = findAgent(data.agent_name)
        if (agent) {
          agent.status = 'running'
          agent.attempts = data.next_attempt || (agent.attempts || 0) + 1
          agent.error = data.reason || ''
        }
      } else if (data.event_type === 'agent_failed') {
        const agent = findAgent(data.agent_name)
        if (agent) {
          agent.status = 'error'
          agent.attempts = data.attempts || agent.attempts || 0
          agent.error = data.error || 'Agent 执行失败'
        }
      } else if (data.event_type === 'agent_finished') {
        const agent = findAgent(data.agent_name)
        if (agent) {
          agent.attempts = data.attempts || agent.attempts || 0
          agent.error = ''
        }
      } else if (data.event_type === 'agent_restored') {
        const agent = findAgent(data.agent_name)
        if (agent) {
          agent.status = 'done'
          agent.error = ''
        }
      }
      harnessEvents.value.push({
        event_type: data.event_type || 'unknown',
        sequence: data.sequence,
        data: data.data || data,
      })
      // 页面只保留最近 20 条，避免长时间运行时无限增长。
      if (harnessEvents.value.length > 20) harnessEvents.value.shift()
      break

    case 'error':
      loadingStatus.value = `⚠️ ${data.message}`
      message.warning(data.message)
      break
  }
}

// NLP 解析自然语言 → 自动填表
const handleParse = async () => {
  if (!freeText.value.trim()) {
    message.warning('请先输入旅行需求')
    return
  }
  parsing.value = true
  try {
    const result = await parseNaturalLanguage(freeText.value)
    if (result.success && result.data) {
      const d = result.data
      formData.city = d.city || ''
      if (d.start_date) formData.start_date = dayjs(d.start_date)
      if (d.end_date) formData.end_date = dayjs(d.end_date)
      if (d.travel_days) formData.travel_days = d.travel_days
      if (d.transportation) formData.transportation = d.transportation
      if (d.accommodation) formData.accommodation = d.accommodation
      if (d.preferences) formData.preferences = d.preferences
      if (d.free_text_input) formData.free_text_input = d.free_text_input

      message.success(`🧠 已解析: ${d.city} ${d.travel_days}天 — 确认后点击规划`)
      inputMode.value = 'form'  // 切换到表单让用户确认
    }
  } catch (e: any) {
    message.error('解析失败: ' + (e.message || '请重试'))
  } finally {
    parsing.value = false
  }
}

const handleSubmit = async () => {
  if (!formData.start_date || !formData.end_date) {
    message.error('请选择日期')
    return
  }

  loading.value = true
  loadingProgress.value = 0
  loadingStatus.value = '正在初始化多智能体系统...'
  resetAgents()

  try {
    const requestData: TripFormData = {
      city: formData.city,
      start_date: formData.start_date.format('YYYY-MM-DD'),
      end_date: formData.end_date.format('YYYY-MM-DD'),
      travel_days: formData.travel_days,
      transportation: formData.transportation,
      accommodation: formData.accommodation,
      preferences: formData.preferences,
      free_text_input: formData.free_text_input
    }

    // 使用 SSE 流式调用，实时接收每个 Agent 的执行状态
    const tripPlan = await generateTripPlanStream(requestData, handleSSEEvent)

    if (tripPlan) {
      sessionStorage.setItem('tripPlan', JSON.stringify(tripPlan))

      const m = metrics.value
      const speedupMsg = m ? ` | 并行加速比 ${m.speedup}x | 总耗时 ${m.total_time}s` : ''
      message.success(`旅行计划生成成功!${speedupMsg}`)

      setTimeout(() => {
        router.push('/result')
      }, 800)
    } else {
      message.error('生成失败，未收到完整数据')
    }
  } catch (error: any) {
    message.error(error.message || '生成旅行计划失败,请稍后重试')
    agents.value.forEach(a => {
      if (a.status === 'running') a.status = 'error'
    })
  } finally {
    setTimeout(() => {
      loading.value = false
    }, 1000)
  }
}
</script>

<style scoped>
.home-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 60px 20px;
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.bg-decoration {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: hidden;
}

.circle {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  animation: float 20s infinite ease-in-out;
}

.circle-1 {
  width: 300px;
  height: 300px;
  top: -100px;
  left: -100px;
  animation-delay: 0s;
}

.circle-2 {
  width: 200px;
  height: 200px;
  top: 50%;
  right: -50px;
  animation-delay: 5s;
}

.circle-3 {
  width: 150px;
  height: 150px;
  bottom: -50px;
  left: 30%;
  animation-delay: 10s;
}

@keyframes float {
  0%, 100% {
    transform: translateY(0) rotate(0deg);
  }
  50% {
    transform: translateY(-30px) rotate(180deg);
  }
}

/* 页面标题 */
.page-header {
  text-align: center;
  margin-bottom: 50px;
  animation: fadeInDown 0.8s ease-out;
  position: relative;
  z-index: 1;
}

.icon-wrapper {
  margin-bottom: 20px;
}

.icon {
  font-size: 80px;
  display: inline-block;
  animation: bounce 2s infinite;
}

@keyframes bounce {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-20px);
  }
}

.page-title {
  font-size: 56px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 16px;
  text-shadow: 3px 3px 6px rgba(0, 0, 0, 0.3);
  letter-spacing: 2px;
}

.page-subtitle {
  font-size: 20px;
  color: rgba(255, 255, 255, 0.95);
  margin: 0;
  font-weight: 300;
}

/* 输入模式切换 */
.mode-switch {
  text-align: center;
  margin-bottom: 32px;
}

/* 自由输入区域 */
.free-input-section {
  padding: 24px;
  background: linear-gradient(135deg, #e8f5e9 0%, #f1f8e9 100%);
  border: 2px dashed #4caf50;
  border-radius: 16px;
  margin-bottom: 24px;
  text-align: center;
}

.free-input-label {
  font-size: 16px;
  font-weight: 600;
  color: #2e7d32;
  margin-bottom: 16px;
}

.free-textarea {
  border-radius: 12px !important;
  font-size: 16px !important;
  margin-bottom: 16px;
}

.parse-button {
  border-radius: 24px;
  height: 44px;
  padding: 0 32px;
  font-size: 16px;
  background: linear-gradient(135deg, #4caf50, #2e7d32);
  border: none;
}

.parse-button:hover {
  background: linear-gradient(135deg, #66bb6a, #388e3c);
}

/* 表单卡片 */
.form-card {
  max-width: 1400px;
  margin: 0 auto;
  border-radius: 24px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.4);
  animation: fadeInUp 0.8s ease-out;
  position: relative;
  z-index: 1;
  backdrop-filter: blur(10px);
  background: rgba(255, 255, 255, 0.98) !important;
}

/* 表单分区 */
.form-section {
  margin-bottom: 32px;
  padding: 24px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 16px;
  border: 1px solid #e8e8e8;
  transition: all 0.3s ease;
}

.form-section:hover {
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.15);
  transform: translateY(-2px);
}

.section-header {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid #667eea;
}

.section-icon {
  font-size: 24px;
  margin-right: 12px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

/* 表单标签 */
.form-label {
  font-size: 15px;
  font-weight: 500;
  color: #555;
}

/* 自定义输入框 */
.custom-input :deep(.ant-input),
.custom-input :deep(.ant-picker) {
  border-radius: 12px;
  border: 2px solid #e8e8e8;
  transition: all 0.3s ease;
}

.custom-input :deep(.ant-input:hover),
.custom-input :deep(.ant-picker:hover) {
  border-color: #667eea;
}

.custom-input :deep(.ant-input:focus),
.custom-input :deep(.ant-picker-focused) {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

/* 自定义选择框 */
.custom-select :deep(.ant-select-selector) {
  border-radius: 12px !important;
  border: 2px solid #e8e8e8 !important;
  transition: all 0.3s ease;
}

.custom-select:hover :deep(.ant-select-selector) {
  border-color: #667eea !important;
}

.custom-select :deep(.ant-select-focused .ant-select-selector) {
  border-color: #667eea !important;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1) !important;
}

/* 天数显示 - 紧凑版 */
.days-display-compact {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  color: white;
}

.days-display-compact .days-value {
  font-size: 24px;
  font-weight: 700;
  margin-right: 4px;
}

.days-display-compact .days-unit {
  font-size: 14px;
}

/* 偏好标签 */
.preference-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.custom-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.preference-tag :deep(.ant-checkbox-wrapper) {
  margin: 0 !important;
  padding: 8px 16px;
  border: 2px solid #e8e8e8;
  border-radius: 20px;
  transition: all 0.3s ease;
  background: white;
  font-size: 14px;
}

.preference-tag :deep(.ant-checkbox-wrapper:hover) {
  border-color: #667eea;
  background: #f5f7ff;
}

.preference-tag :deep(.ant-checkbox-wrapper-checked) {
  border-color: #667eea;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

/* 自定义文本域 */
.custom-textarea :deep(.ant-input) {
  border-radius: 12px;
  border: 2px solid #e8e8e8;
  transition: all 0.3s ease;
}

.custom-textarea :deep(.ant-input:hover) {
  border-color: #667eea;
}

.custom-textarea :deep(.ant-input:focus) {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

/* 提交按钮 */
.submit-button {
  height: 56px;
  border-radius: 28px;
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.4);
  transition: all 0.3s ease;
}

.submit-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 32px rgba(102, 126, 234, 0.5);
}

.submit-button:active {
  transform: translateY(0);
}

.button-icon {
  margin-right: 8px;
  font-size: 20px;
}

/* 加载容器 */
.loading-container {
  text-align: center;
  padding: 24px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 16px;
  border: 2px dashed #667eea;
}

.loading-status {
  margin-top: 16px;
  color: #667eea;
  font-size: 18px;
  font-weight: 500;
}

/* Orchestrator 调度决策面板 */
.orchestration-panel {
  margin-top: 16px;
  padding: 16px;
  background: linear-gradient(135deg, #e8f5e9 0%, #f1f8e9 100%);
  border: 2px solid #4caf50;
  border-radius: 12px;
  text-align: left;
}

.orch-header {
  font-size: 16px;
  font-weight: 700;
  color: #2e7d32;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.orch-count {
  font-size: 13px;
  background: #4caf50;
  color: white;
  padding: 2px 10px;
  border-radius: 12px;
}

.orch-reasoning {
  font-size: 13px;
  color: #555;
  margin-bottom: 10px;
  line-height: 1.5;
}

.orch-agents {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.orch-agent-tag {
  display: inline-block;
  padding: 4px 12px;
  background: white;
  border: 1px solid #a5d6a7;
  border-radius: 16px;
  font-size: 13px;
  color: #2e7d32;
}

/* Agent 实时状态面板 */
.agent-status-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 20px;
}

.agent-status-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: white;
  border-radius: 12px;
  border: 2px solid #e8e8e8;
  transition: all 0.3s ease;
  text-align: left;
}

.agent-status-card.agent-running {
  border-color: #1890ff;
  box-shadow: 0 0 12px rgba(24, 144, 255, 0.15);
  animation: pulse-border 1.5s infinite;
}

.agent-status-card.agent-done {
  border-color: #52c41a;
  background: #f6ffed;
}

.agent-status-card.agent-error {
  border-color: #ff4d4f;
  background: #fff2f0;
}

.agent-status-card.agent-fallback {
  border-color: #fa8c16;
  background: #fff7e6;
}

.agent-icon {
  font-size: 28px;
  flex-shrink: 0;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-name {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin-bottom: 4px;
}

.agent-state {
  font-size: 13px;
  color: #666;
  display: flex;
  align-items: center;
  gap: 6px;
}

.state-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.state-dot.idle { background: #d9d9d9; }
.state-dot.running {
  background: #1890ff;
  animation: blink 0.8s infinite;
}
.state-dot.done { background: #52c41a; }
.state-dot.fallback { background: #fa8c16; }
.state-dot.error { background: #ff4d4f; }

.agent-time {
  color: #52c41a;
  font-weight: 600;
  margin-left: 4px;
}

.agent-attempts {
  margin-left: 8px;
  color: #8c8c8c;
  font-size: 12px;
}

.agent-error-message {
  margin-top: 6px;
  padding: 5px 8px;
  color: #cf1322;
  background: #fff1f0;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
  word-break: break-word;
}

.harness-current-phase {
  margin-top: 8px;
  color: #595959;
  font-size: 12px;
}

.agent-summary {
  font-size: 12px;
  color: #999;
  margin-top: 6px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.metrics-badge {
  margin-top: 16px;
  padding: 10px 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 24px;
  font-size: 14px;
  display: inline-block;
}

.harness-panel {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid #d9d9d9;
  border-radius: 12px;
  background: #fafafa;
  text-align: left;
  max-height: 220px;
  overflow-y: auto;
}

.harness-title {
  margin-bottom: 8px;
  font-weight: 600;
  color: #262626;
}

.harness-event {
  display: flex;
  gap: 10px;
  padding: 5px 0;
  color: #595959;
  font-size: 12px;
}

.harness-event-type {
  min-width: 145px;
  color: #1677ff;
  font-family: monospace;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

@keyframes pulse-border {
  0%, 100% { border-color: #1890ff; box-shadow: 0 0 8px rgba(24, 144, 255, 0.1); }
  50% { border-color: #69c0ff; box-shadow: 0 0 16px rgba(24, 144, 255, 0.25); }
}

/* 响应式: 小屏幕单列 */
@media (max-width: 768px) {
  .agent-status-grid {
    grid-template-columns: 1fr;
  }
}

/* 动画 */
@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>

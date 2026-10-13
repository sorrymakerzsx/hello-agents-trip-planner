import axios from 'axios'
import type { TripFormData, TripPlanResponse } from '@/types'

// 同源部署时走 Nginx 的 /api 代理；本地开发时由 Vite 代理到后端。
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 360000, // 6分钟超时，与后端LLM_TIMEOUT匹配
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    console.log('发送请求:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    console.log('收到响应:', response.status, response.config.url)
    return response
  },
  (error) => {
    console.error('响应错误:', error.response?.status, error.message)
    return Promise.reject(error)
  }
)

/**
 * 生成旅行计划 (一次性返回)
 */
export async function generateTripPlan(formData: TripFormData): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/trip/plan', formData)
    return response.data
  } catch (error: any) {
    console.error('生成旅行计划失败:', error)
    throw new Error(error.response?.data?.detail || error.message || '生成旅行计划失败')
  }
}

/** SSE 事件类型 */
export interface SSEEvent {
  event: string
  data: any
}

/**
 * 生成旅行计划 (SSE流式推送)
 *
 * 通过 fetch + ReadableStream 消费后端 SSE 事件流。
 * 每收到一个事件就调用 onEvent 回调，前端可以实时更新 UI。
 *
 * @param formData 旅行请求参数
 * @param onEvent  事件回调 (agent_start, agent_done, phase, complete, metrics, error)
 * @returns        最终旅行计划数据 (从 complete 事件中提取)
 */
export async function generateTripPlanStream(
  formData: TripFormData,
  onEvent: (event: SSEEvent) => void
): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/trip/plan/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // SSE 事件以 \n\n 分隔
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''  // 最后一段可能不完整，保留

    for (const part of parts) {
      if (!part.trim()) continue

      // 解析 SSE 帧: "event: <type>\ndata: <json>"
      const eventMatch = part.match(/^event:\s*(.+)$/m)
      const dataMatch = part.match(/^data:\s*(.+)$/m)

      if (eventMatch && dataMatch) {
        const eventType = eventMatch[1].trim()
        const data = JSON.parse(dataMatch[1].trim())
        onEvent({ event: eventType, data })

        if (eventType === 'complete') {
          return data  // 返回最终的 TripPlan
        }
      }
    }
  }

  throw new Error('SSE stream ended without complete event')
}

/**
 * 自然语言解析 — 一句话 → 结构化旅行参数
 */
export async function parseNaturalLanguage(text: string): Promise<any> {
  const response = await apiClient.post('/api/trip/parse', { text })
  return response.data
}

/**
 * 健康检查
 */
export async function healthCheck(): Promise<any> {
  try {
    const response = await apiClient.get('/health')
    return response.data
  } catch (error: any) {
    console.error('健康检查失败:', error)
    throw new Error(error.message || '健康检查失败')
  }
}

export default apiClient

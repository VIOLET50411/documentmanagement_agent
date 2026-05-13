import axios, { type AxiosError, type AxiosRequestConfig } from "axios"
import { useAuthStore } from "@/stores/auth"
import { getApiBaseUrl } from "@/mobile/capacitor"

type ApiResponse<T> = T
type TimedAxiosRequestConfig = AxiosRequestConfig & {
  metadata?: {
    startedAt: number
  }
}

type HttpTraceEntry = {
  method: string
  url: string
  status: number
  durationMs: number
  startedAt: string
  responseTimeHeader?: string
  serverTiming?: string
}

const TRACE_LIMIT = 200
const RECENT_HTTP_TRACES: HttpTraceEntry[] = []

const http = axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
})

http.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  const timedConfig = config as TimedAxiosRequestConfig
  if (authStore.token) {
    const headers = config.headers as Record<string, string | undefined> | undefined
    if (headers) {
      headers.Authorization = `Bearer ${authStore.token}`
    } else {
      config.headers = { Authorization: `Bearer ${authStore.token}` } as typeof config.headers
    }
  }
  timedConfig.metadata = { startedAt: Date.now() }
  return config
})

http.interceptors.response.use(
  (response) => {
    recordHttpTrace(response.config as TimedAxiosRequestConfig, response.status, response.headers as Record<string, unknown> | undefined)
    return response.data
  },
  async (error: AxiosError) => {
    const authStore = useAuthStore()
    const originalConfig = error.config as (TimedAxiosRequestConfig & { _retry?: boolean }) | undefined

    if (originalConfig) {
      recordHttpTrace(originalConfig, error.response?.status || 0, error.response?.headers as Record<string, unknown> | undefined)
    }

    if (error.response?.status === 401 && originalConfig && !originalConfig._retry && authStore.refreshToken) {
      originalConfig._retry = true
      const refreshed = await authStore.refreshSession()
      if (refreshed && authStore.token) {
        const headers = originalConfig.headers as Record<string, string | undefined> | undefined
        if (headers) {
          headers.Authorization = `Bearer ${authStore.token}`
        } else {
          originalConfig.headers = { Authorization: `Bearer ${authStore.token}` } as typeof originalConfig.headers
        }
        return http.request(originalConfig)
      }
    }

    if (error.response?.status === 401) {
      authStore.logout()
    }
    return Promise.reject(error)
  }
)

export function apiGet<T = any>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return http.get<T, ApiResponse<T>>(url, config)
}

export function apiPost<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return http.post<T, ApiResponse<T>>(url, data, config)
}

export function apiPatch<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return http.patch<T, ApiResponse<T>>(url, data, config)
}

export function apiDelete<T = any>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return http.delete<T, ApiResponse<T>>(url, config)
}

export default http

export function getRecentHttpTraces(): HttpTraceEntry[] {
  return [...RECENT_HTTP_TRACES]
}

function recordHttpTrace(config: TimedAxiosRequestConfig, status: number, headers?: Record<string, unknown>) {
  const startedAt = config.metadata?.startedAt
  if (!startedAt) return
  const durationMs = Date.now() - startedAt
  const entry: HttpTraceEntry = {
    method: String(config.method || "get").toUpperCase(),
    url: String(config.url || ""),
    status,
    durationMs,
    startedAt: new Date(startedAt).toISOString(),
    responseTimeHeader: readHeader(headers, "x-response-time"),
    serverTiming: readHeader(headers, "server-timing"),
  }
  RECENT_HTTP_TRACES.unshift(entry)
  if (RECENT_HTTP_TRACES.length > TRACE_LIMIT) {
    RECENT_HTTP_TRACES.length = TRACE_LIMIT
  }
  if (typeof window !== "undefined") {
    ;(window as typeof window & { __DOCMIND_HTTP_TRACES__?: HttpTraceEntry[] }).__DOCMIND_HTTP_TRACES__ = RECENT_HTTP_TRACES
  }
  if (durationMs >= 800) {
    console.warn("[docmind][http][slow]", entry)
  }
}

function readHeader(headers: Record<string, unknown> | undefined, key: string): string | undefined {
  if (!headers) return undefined
  const value = headers[key]
  return typeof value === "string" ? value : undefined
}

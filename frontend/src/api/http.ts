import axios, { type AxiosError, type AxiosRequestConfig } from "axios"
import { useAuthStore } from "@/stores/auth"
import { getApiBaseUrl } from "@/mobile/capacitor"

type ApiResponse<T> = T

const http = axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
})

http.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.token) {
    const headers = config.headers as Record<string, string | undefined> | undefined
    if (headers) {
      headers.Authorization = `Bearer ${authStore.token}`
    } else {
      config.headers = { Authorization: `Bearer ${authStore.token}` } as typeof config.headers
    }
  }
  return config
})

http.interceptors.response.use(
  (response) => response.data,
  async (error: AxiosError) => {
    const authStore = useAuthStore()
    const originalConfig = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined

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

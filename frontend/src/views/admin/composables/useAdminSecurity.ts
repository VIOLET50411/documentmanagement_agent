import { reactive } from "vue"
import { adminApi } from "@/api/admin"

type GenericMap = Record<string, any>

export function useAdminSecurity() {
  const state = reactive({
    securityEvents: [] as GenericMap[],
    securityTotal: 0,
    securityPage: 0,
    securityPageSize: 20,
    loadingSecurity: false,
    securityAlerts: [] as GenericMap[],
    securityFilters: {
      severity: "",
      action: "",
      result: "",
    },
    error: ""
  })

  async function loadSecurityEvents(resetPage = true) {
    state.loadingSecurity = true
    state.error = ""
    try {
      const offset = resetPage ? 0 : state.securityPage * state.securityPageSize
      if (resetPage) state.securityPage = 0
      const response = await adminApi.getSecurityEvents({
        limit: state.securityPageSize,
        offset,
        severity: state.securityFilters.severity || undefined,
        action: state.securityFilters.action || undefined,
        result: state.securityFilters.result || undefined,
      })
      state.securityEvents = response.events || []
      state.securityTotal = response.total || 0
      const alerts = await adminApi.getSecurityAlerts({ limit: 20, offset: 0 })
      state.securityAlerts = alerts.alerts || []
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "加载安全事件失败。"
    } finally {
      state.loadingSecurity = false
    }
  }

  async function changeSecurityPage(delta: number) {
    const nextPage = state.securityPage + delta
    if (nextPage < 0) return
    state.securityPage = nextPage
    await loadSecurityEvents(false)
  }

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  return {
    state,
    loadSecurityEvents,
    changeSecurityPage,
    formatDate
  }
}

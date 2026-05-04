import { reactive, computed } from "vue"
import { adminApi } from "@/api/admin"

type GenericMap = Record<string, any>

export function useAdminOverview() {
  const state = reactive({
    dashboardStats: {} as GenericMap,
    analytics: {} as GenericMap,
    loadingOverview: false,
    error: ""
  })

  const statCards = computed(() => [
    { label: "总查询数", value: state.analytics.total_queries ?? 0 },
    { label: "文档总数", value: state.analytics.total_documents ?? 0, tab: 'pipeline' },
    { label: "已完成文档", value: state.analytics.ready_documents ?? 0, tab: 'pipeline' },
    { label: "处理中", value: state.analytics.processing_documents ?? 0, tab: 'pipeline' },
    { label: "失败文档", value: state.analytics.failed_documents ?? 0, tab: 'pipeline' },
    { label: "平均满意度", value: state.analytics.avg_satisfaction ?? "-" },
    { label: "缓存命中率", value: `${((state.analytics.cache_hit_rate ?? 0) * 100).toFixed(1)}%` },
    { label: "安全事件数", value: state.analytics.security_event_count ?? 0, tab: 'security' },
  ])

  async function loadOverview() {
    state.loadingOverview = true
    state.error = ""
    try {
      const res = await adminApi.getAnalytics()
      state.analytics = res || {}
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "加载平台概览失败。"
    } finally {
      state.loadingOverview = false
    }
  }

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  return {
    state,
    statCards,
    loadOverview,
    formatDate
  }
}

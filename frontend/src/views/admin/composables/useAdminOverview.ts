import { computed, reactive } from "vue"
import { adminApi } from "@/api/admin"
import { getApiErrorMessage } from "@/utils/adminUi"

type GenericMap = Record<string, any>

export function useAdminOverview() {
  const state = reactive({
    dashboardStats: {} as GenericMap,
    analytics: {} as GenericMap,
    readiness: null as GenericMap | null,
    retrievalIntegrity: null as GenericMap | null,
    loadingOverview: false,
    loadingIntegrity: false,
    runningAction: "",
    actionMessage: "",
    error: "",
  })

  const statCards = computed(() => [
    { label: "总查询数", value: state.analytics.total_queries ?? 0 },
    { label: "文档总数", value: state.analytics.total_documents ?? 0, tab: "pipeline" },
    { label: "已完成文档", value: state.analytics.ready_documents ?? 0, tab: "pipeline" },
    { label: "处理中", value: state.analytics.processing_documents ?? 0, tab: "pipeline" },
    { label: "失败文档", value: state.analytics.failed_documents ?? 0, tab: "pipeline" },
    { label: "平均满意度", value: state.analytics.avg_satisfaction ?? "-" },
    { label: "缓存命中率", value: `${((state.analytics.cache_hit_rate ?? 0) * 100).toFixed(1)}%` },
    { label: "安全事件数", value: state.analytics.security_event_count ?? 0, tab: "security" },
  ])

  async function loadRetrievalIntegrity() {
    if (state.loadingIntegrity) return

    state.loadingIntegrity = true
    try {
      state.retrievalIntegrity = (await adminApi.getRetrievalIntegrity(12)) || null
    } catch {
      // 即使完整性采样较慢，也保持总览页可交互。
    } finally {
      state.loadingIntegrity = false
    }
  }

  async function loadOverview() {
    state.loadingOverview = true
    state.error = ""
    try {
      const [analyticsRes, readinessRes] = await Promise.all([
        adminApi.getAnalytics(),
        adminApi.getPlatformReadiness(),
      ])
      state.analytics = analyticsRes || {}
      state.readiness = readinessRes || null
      void loadRetrievalIntegrity()
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "加载平台总览失败，请稍后重试。")
    } finally {
      state.loadingOverview = false
    }
  }

  async function runOpsAction(action: "reindex" | "retry_failed" | "evaluation" | "refresh_health") {
    state.runningAction = action
    state.error = ""
    state.actionMessage = ""
    try {
      if (action === "reindex") {
        await adminApi.reindexDocuments()
        state.actionMessage = "已触发全租户索引重建。"
      } else if (action === "retry_failed") {
        await adminApi.retryFailedPipelineJobs(20, true)
        state.actionMessage = "已触发失败和部分失败文档的批量重试。"
      } else if (action === "evaluation") {
        const result = await adminApi.runEvaluationAsync()
        state.actionMessage = result?.task_id ? `已启动评估任务：${result.task_id}` : "已启动评估任务。"
      } else {
        state.actionMessage = "已刷新平台就绪度和检索体检数据。"
      }
      await loadOverview()
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "平台操作没有成功，请稍后再试。")
    } finally {
      state.runningAction = ""
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
    loadRetrievalIntegrity,
    runOpsAction,
    formatDate,
  }
}

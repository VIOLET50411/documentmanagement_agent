import { reactive } from "vue"
import { adminApi } from "@/api/admin"

type GenericMap = Record<string, any>

export function useAdminEvaluation() {
  const state = reactive({
    evaluationLatest: null as GenericMap | null,
    evaluationHistory: [] as GenericMap[],
    evaluationSummary: [] as GenericMap[],
    runtimeMetricsSummary: null as GenericMap | null,
    runtimeMetricsHistory: [] as GenericMap[],
    evaluating: false,
    evalError: "",
    error: "",
  })

  async function loadEvaluation() {
    state.error = ""
    try {
      const [latestRes, historyRes, summaryRes, metricsRes, metricsHistoryRes] = await Promise.all([
        adminApi.getLatestEvaluation(),
        adminApi.getEvaluationHistory(10),
        adminApi.getEvaluationGateSummary(10),
        adminApi.getRuntimeMetrics(),
        adminApi.getRuntimeMetricsHistory(10),
      ])
      state.evaluationLatest = latestRes || null
      state.evaluationHistory = historyRes || []
      state.evaluationSummary = summaryRes || []
      state.runtimeMetricsSummary = metricsRes || null
      state.runtimeMetricsHistory = metricsHistoryRes || []
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "加载评估指标失败。"
    }
  }

  async function pollEvaluationTask(taskId: string) {
    try {
      const payload = await adminApi.getEvaluationTask(taskId)
      const status = payload?.item?.status || ""
      if (status === "completed") {
        state.evaluating = false
        await loadEvaluation()
        return
      }
      if (status === "failed" || status === "killed") {
        state.evaluating = false
        state.evalError = payload?.item?.error || "评估失败"
        return
      }
      window.setTimeout(() => void pollEvaluationTask(taskId), 3000)
    } catch (err: any) {
      state.evalError = err?.response?.data?.detail || "轮询评估任务失败"
      state.evaluating = false
    }
  }

  async function runEvaluation() {
    state.evaluating = true
    state.evalError = ""
    try {
      const result = await adminApi.runEvaluationAsync()
      if (result?.task_id) {
        await pollEvaluationTask(result.task_id)
      } else {
        await loadEvaluation()
        state.evaluating = false
      }
    } catch (err: any) {
      state.evalError = err?.response?.data?.detail || "触发评估失败。"
      state.evaluating = false
    }
  }

  function downloadRuntimeMetrics() {
    try {
      const blob = new Blob([JSON.stringify(state.runtimeMetricsHistory || [], null, 2)], {
        type: "application/json;charset=utf-8",
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = "runtime_metrics_history.json"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch {
      state.evalError = "导出评估数据失败。"
    }
  }

  function formatPercent(value: number | null | undefined) {
    if (value === null || value === undefined) return "-"
    return `${(Number(value) * 100).toFixed(1)}%`
  }

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  return {
    state,
    loadEvaluation,
    runEvaluation,
    downloadRuntimeMetrics,
    formatPercent,
    formatDate,
  }
}

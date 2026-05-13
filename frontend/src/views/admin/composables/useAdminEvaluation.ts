import { reactive } from "vue"
import { adminApi } from "@/api/admin"
import { getApiErrorMessage } from "@/utils/adminUi"

type GenericMap = Record<string, any>

function getFriendlyTaskError(rawError: string | null | undefined) {
  if (!rawError) return "这次检查没有成功完成，请稍后再试。"
  const text = String(rawError)
  if (/timeout|timed out|超时/i.test(text)) return "这次检查超时了。通常是样本太多，或者模型响应太慢。可以先减少样本量再试一次。"
  if (/connection|network|redis|postgres|database|connect/i.test(text)) return "这次检查没有跑起来，更像是服务连接异常。请稍后再试，或检查后台服务是否正常。"
  if (/permission|forbidden|unauthorized|403|401/i.test(text)) return "当前账号没有权限执行这一步。"
  return `这次检查没有成功完成：${text}`
}

export function useAdminEvaluation() {
  const state = reactive({
    evaluationLatest: null as GenericMap | null,
    evaluationHistory: [] as GenericMap[],
    evaluationSummary: [] as GenericMap[],
    evaluationDatasetSamples: [] as GenericMap[],
    evaluationDatasetSamplesTotal: 0,
    evaluationDatasetSamplesPath: "",
    updatingSampleId: "",
    deletingSampleId: "",
    evaluationRunConfig: {
      sampleLimit: 100,
      prioritizeAllManualSamples: false,
      manualSampleRatio: 1,
    },
    runtimeMetricsSummary: null as GenericMap | null,
    runtimeMetricsHistory: [] as GenericMap[],
    evaluating: false,
    evalError: "",
    error: "",
  })

  async function loadEvaluation() {
    state.error = ""
    try {
      const [latestRes, historyRes, summaryRes, datasetSamplesRes, metricsRes, metricsHistoryRes] = await Promise.all([
        adminApi.getLatestEvaluation(),
        adminApi.getEvaluationHistory(10),
        adminApi.getEvaluationGateSummary(10),
        adminApi.getEvaluationDatasetSamples(12),
        adminApi.getRuntimeMetrics(),
        adminApi.getRuntimeMetricsHistory(10),
      ])
      state.evaluationLatest = latestRes || null
      state.evaluationHistory = historyRes || []
      state.evaluationSummary = summaryRes || []
      state.evaluationDatasetSamples = datasetSamplesRes?.items || []
      state.evaluationDatasetSamplesTotal = datasetSamplesRes?.total || 0
      state.evaluationDatasetSamplesPath = datasetSamplesRes?.path || ""
      const generatedFrom = latestRes?.generated_from || {}
      state.evaluationRunConfig.sampleLimit = Number(generatedFrom.sample_limit || 100)
      state.evaluationRunConfig.prioritizeAllManualSamples = Boolean(generatedFrom.prioritize_all_manual_samples)
      state.evaluationRunConfig.manualSampleRatio = Number(generatedFrom.manual_sample_ratio ?? 1)
      state.runtimeMetricsSummary = metricsRes || null
      state.runtimeMetricsHistory = metricsHistoryRes || []
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "检查数据暂时没有加载出来，请稍后刷新页面再试。")
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
        state.evalError = getFriendlyTaskError(payload?.item?.error)
        return
      }
      window.setTimeout(() => void pollEvaluationTask(taskId), 3000)
    } catch (err: any) {
      state.evalError = getApiErrorMessage(err, "检查已经发起，但暂时拿不到进度。请稍后刷新页面确认结果。")
      state.evaluating = false
    }
  }

  async function runEvaluation() {
    state.evaluating = true
    state.evalError = ""
    try {
      const result = await adminApi.runEvaluationAsync(
        Math.max(Number(state.evaluationRunConfig.sampleLimit || 100), 1),
        Boolean(state.evaluationRunConfig.prioritizeAllManualSamples),
        Math.min(Math.max(Number(state.evaluationRunConfig.manualSampleRatio ?? 1), 0), 1),
      )
      if (result?.task_id) {
        await pollEvaluationTask(result.task_id)
      } else {
        await loadEvaluation()
        state.evaluating = false
      }
    } catch (err: any) {
      state.evalError = getApiErrorMessage(err, "检查没有成功发起。请检查配置后再试。")
      state.evaluating = false
    }
  }

  async function refreshManualSamples(limit = 12) {
    const datasetSamplesRes = await adminApi.getEvaluationDatasetSamples(limit)
    state.evaluationDatasetSamples = datasetSamplesRes?.items || []
    state.evaluationDatasetSamplesTotal = datasetSamplesRes?.total || 0
    state.evaluationDatasetSamplesPath = datasetSamplesRes?.path || ""
  }

  async function updateManualSample(sampleId: string, payload: GenericMap) {
    state.updatingSampleId = sampleId
    try {
      await adminApi.updateEvaluationDatasetSample(sampleId, payload)
      await refreshManualSamples()
    } finally {
      state.updatingSampleId = ""
    }
  }

  async function deleteManualSample(sampleId: string) {
    state.deletingSampleId = sampleId
    try {
      await adminApi.deleteEvaluationDatasetSample(sampleId)
      await refreshManualSamples()
    } finally {
      state.deletingSampleId = ""
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
      link.download = "qa_check_runtime_history.json"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch {
      state.evalError = "导出运行记录失败，请稍后再试。"
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
    refreshManualSamples,
    updateManualSample,
    deleteManualSample,
    downloadRuntimeMetrics,
    formatPercent,
    formatDate,
  }
}

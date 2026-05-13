import { computed, reactive } from "vue"
import { adminApi } from "@/api/admin"
import { getApiErrorMessage, pipelineStatusLabel } from "@/utils/adminUi"

type GenericMap = Record<string, any>

export function useAdminPipeline() {
  const state = reactive({
    pipeline: {} as GenericMap,
    pipelineJobs: [] as GenericMap[],
    pipelineTotal: 0,
    pipelinePage: 0,
    pipelinePageSize: 20,
    pipelineFilterStatus: "",
    loadingPipeline: false,
    retryingFailed: false,
    pipelineFailureSummary: [] as GenericMap[],
    retryingSignature: "",
    error: "",
  })

  const pipelineCards = computed(() => [
    { label: "正在处理", value: state.pipeline.active ?? 0 },
    { label: "等待处理", value: state.pipeline.queued ?? 0 },
    { label: "处理失败", value: state.pipeline.failed ?? 0 },
    { label: "已经完成", value: state.pipeline.completed ?? 0 },
  ])

  async function loadPipelineStatus() {
    state.loadingPipeline = true
    try {
      const res = await adminApi.getPipelineStatus()
      state.pipeline = res
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "处理状态暂时没加载出来，请稍后刷新页面再试。")
    } finally {
      state.loadingPipeline = false
    }
  }

  async function loadPipelineJobs() {
    state.loadingPipeline = true
    state.error = ""
    try {
      const [response, summary] = await Promise.all([
        adminApi.getPipelineJobs({
          limit: state.pipelinePageSize,
          offset: state.pipelinePage * state.pipelinePageSize,
          status: state.pipelineFilterStatus || undefined,
        }),
        adminApi.getPipelineFailureSummary(20),
      ])
      state.pipelineJobs = response.jobs || []
      state.pipelineTotal = response.total || 0
      state.pipelineFailureSummary = summary.items || []
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "任务列表暂时没加载出来，请稍后再试。")
    } finally {
      state.loadingPipeline = false
    }
  }

  async function applyPipelineFilter() {
    state.pipelinePage = 0
    await loadPipelineJobs()
  }

  async function changePipelinePage(delta: number) {
    const nextPage = state.pipelinePage + delta
    if (nextPage < 0) return
    state.pipelinePage = nextPage
    await loadPipelineJobs()
  }

  async function retryPipelineJob(job: GenericMap) {
    state.error = ""
    try {
      await adminApi.retryPipelineJob(job.doc_id)
      await Promise.all([loadPipelineJobs(), loadPipelineStatus()])
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "这条任务没有重试成功，请稍后再试。")
    }
  }

  async function retryFailedJobs() {
    state.retryingFailed = true
    state.error = ""
    try {
      await adminApi.retryFailedPipelineJobs(20, true)
      await Promise.all([loadPipelineJobs(), loadPipelineStatus()])
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "批量重试没有成功，请稍后再试。")
    } finally {
      state.retryingFailed = false
    }
  }

  async function retryBySignature(signature: string) {
    state.retryingSignature = signature
    state.error = ""
    try {
      await adminApi.retryPipelineBySignature(signature, 20)
      await Promise.all([loadPipelineJobs(), loadPipelineStatus()])
    } catch (err: any) {
      state.error = getApiErrorMessage(err, "同类失败任务重试没有成功，请稍后再试。")
    } finally {
      state.retryingSignature = ""
    }
  }

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  function readablePipelineStatus(status: string) {
    return pipelineStatusLabel(status)
  }

  function readableJobDetail(job: GenericMap) {
    const detail = String(job.detail || job.error_message || "").trim()
    if (!detail) return "暂时没有更多信息"

    const normalized = detail.toLowerCase()
    const knownMap: Array<[RegExp, string]> = [
      [/timeout|timed out/, "处理超时，任务没有在预期时间内完成。"],
      [/permission|forbidden|denied/, "当前任务缺少所需权限。"],
      [/network|connect|connection|unreachable/, "处理过程中连接后端服务失败。"],
      [/parse|parser|unsupported|decode/, "文件解析失败，资料格式可能不受支持。"],
      [/chunk|split/, "切分文本时失败，原文结构可能不完整。"],
      [/index|embedding|vector|milvus|elasticsearch/, "入库或检索索引阶段失败。"],
      [/virus|clamav/, "文件安全检查没有通过。"],
      [/empty|no content/, "资料内容为空，无法继续处理。"],
    ]

    const mapped = knownMap.find(([pattern]) => pattern.test(normalized))
    return mapped?.[1] || detail
  }

  function readableFailureSignature(signature: string | null | undefined) {
    const value = String(signature || "").trim()
    if (!value) return "未分类失败"

    const normalized = value.toLowerCase()
    const knownMap: Array<[RegExp, string]> = [
      [/timeout|timed out/, "处理超时"],
      [/permission|forbidden|denied/, "权限不足"],
      [/network|connect|connection|unreachable/, "后端连接失败"],
      [/parse|parser|unsupported|decode/, "文件解析失败"],
      [/chunk|split/, "文本切分失败"],
      [/index|embedding|vector|milvus|elasticsearch/, "入库索引失败"],
      [/virus|clamav/, "安全检查失败"],
      [/empty|no content/, "资料内容为空"],
    ]

    const mapped = knownMap.find(([pattern]) => pattern.test(normalized))
    return mapped?.[1] || "其他处理失败"
  }

  return {
    state,
    pipelineCards,
    loadPipelineStatus,
    loadPipelineJobs,
    applyPipelineFilter,
    changePipelinePage,
    retryPipelineJob,
    retryFailedJobs,
    retryBySignature,
    formatDate,
    readablePipelineStatus,
    readableJobDetail,
    readableFailureSignature,
  }
}

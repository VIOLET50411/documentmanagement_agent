import { reactive, computed } from "vue"
import { adminApi } from "@/api/admin"

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
    { label: "活跃任务", value: state.pipeline.active ?? 0 },
    { label: "排队任务", value: state.pipeline.queued ?? 0 },
    { label: "失败任务", value: state.pipeline.failed ?? 0 },
    { label: "完成任务", value: state.pipeline.completed ?? 0 },
  ])

  async function loadPipelineStatus() {
    state.loadingPipeline = true
    try {
      const res = await adminApi.getPipelineStatus()
      state.pipeline = res
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "加载管线状态失败。"
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
      state.error = err?.response?.data?.detail || "加载任务失败。"
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
      state.error = err?.response?.data?.detail || "重试任务失败。"
    }
  }

  async function retryFailedJobs() {
    state.retryingFailed = true
    state.error = ""
    try {
      await adminApi.retryFailedPipelineJobs(20, true)
      await Promise.all([loadPipelineJobs(), loadPipelineStatus()])
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "批量重试失败。"
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
      state.error = err?.response?.data?.detail || "按错误类型重试失败。"
    } finally {
      state.retryingSignature = ""
    }
  }

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
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
  }
}

import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { adminApi } from "@/api/admin"
import { getApiErrorMessage } from "@/utils/adminUi"

type GenericRecord = Record<string, any>

export const useRuntimeStore = defineStore("runtime", () => {
  const TOOL_SUMMARY_MAX_AGE_MS = 10_000
  const CHECKPOINT_SUMMARY_MAX_AGE_MS = 10_000
  const loadingToolSummary = ref(false)
  const loadingCheckpointSummary = ref(false)
  const loadingReplay = ref(false)
  const error = ref("")
  const toolDecisionSummary = ref<GenericRecord | null>(null)
  const checkpointSummary = ref<GenericRecord[]>([])
  const replayTraceId = ref("")
  const replayEvents = ref<GenericRecord[]>([])
  const lastToolSummaryLoadedAt = ref(0)
  const lastCheckpointSummaryLoadedAt = ref(0)
  const toolFilters = ref({
    since_hours: 24,
    decision: "",
    source: "",
    tool_name: "",
    reason: "",
  })

  const toolMatrixRows = computed(() => toolDecisionSummary.value?.matrix_by_tool || [])
  const reasonMatrixRows = computed(() => toolDecisionSummary.value?.matrix_by_reason || [])
  const trendRows = computed(() => toolDecisionSummary.value?.trend_by_hour || [])
  let toolSummaryRequest: Promise<GenericRecord | null> | null = null
  let checkpointSummaryRequest: Promise<GenericRecord[]> | null = null
  let toolSummaryRequestKey = ""
  let checkpointSummaryRequestKey = ""
  let toolSummaryLoadedKey = ""
  let checkpointSummaryLoadedKey = ""

  async function loadToolDecisionSummary(options: { force?: boolean; maxAgeMs?: number } = {}) {
    const requestKey = JSON.stringify(toolFilters.value)
    const maxAgeMs = Math.max(Number(options.maxAgeMs ?? TOOL_SUMMARY_MAX_AGE_MS), 0)
    if (
      !options.force &&
      toolDecisionSummary.value &&
      toolSummaryLoadedKey === requestKey &&
      Date.now() - lastToolSummaryLoadedAt.value <= maxAgeMs
    ) {
      return toolDecisionSummary.value
    }
    if (toolSummaryRequest && toolSummaryRequestKey === requestKey) {
      return toolSummaryRequest
    }

    loadingToolSummary.value = true
    error.value = ""
    toolSummaryRequestKey = requestKey
    const request = (async () => {
      try {
        const payload = await adminApi.getRuntimeToolDecisionSummary(toolFilters.value)
        if (toolSummaryRequestKey === requestKey) {
          toolDecisionSummary.value = payload || null
          lastToolSummaryLoadedAt.value = Date.now()
          toolSummaryLoadedKey = requestKey
        }
      } catch (caught: any) {
        if (toolSummaryRequestKey === requestKey) {
          error.value = getApiErrorMessage(caught, "运行过程的工具使用情况暂时没加载出来，请稍后再试。")
        }
      } finally {
        if (toolSummaryRequest === request) {
          loadingToolSummary.value = false
          toolSummaryRequest = null
          toolSummaryRequestKey = ""
        }
      }
      return toolDecisionSummary.value
    })()
    toolSummaryRequest = request
    return request
  }

  async function loadCheckpointSummary(limit = 50, options: { force?: boolean; maxAgeMs?: number } = {}) {
    const normalizedLimit = Math.max(limit, 1)
    const requestKey = String(normalizedLimit)
    const maxAgeMs = Math.max(Number(options.maxAgeMs ?? CHECKPOINT_SUMMARY_MAX_AGE_MS), 0)
    if (
      !options.force &&
      checkpointSummary.value.length &&
      checkpointSummaryLoadedKey === requestKey &&
      Date.now() - lastCheckpointSummaryLoadedAt.value <= maxAgeMs
    ) {
      return checkpointSummary.value
    }
    if (checkpointSummaryRequest && checkpointSummaryRequestKey === requestKey) {
      return checkpointSummaryRequest
    }

    loadingCheckpointSummary.value = true
    error.value = ""
    checkpointSummaryRequestKey = requestKey
    const request = (async () => {
      try {
        const response = await adminApi.getRuntimeCheckpointSummary(normalizedLimit)
        if (checkpointSummaryRequestKey === requestKey) {
          checkpointSummary.value = response?.items || []
          lastCheckpointSummaryLoadedAt.value = Date.now()
          checkpointSummaryLoadedKey = requestKey
        }
      } catch (caught: any) {
        if (checkpointSummaryRequestKey === requestKey) {
          error.value = getApiErrorMessage(caught, "恢复点信息暂时没加载出来，请稍后再试。")
        }
      } finally {
        if (checkpointSummaryRequest === request) {
          loadingCheckpointSummary.value = false
          checkpointSummaryRequest = null
          checkpointSummaryRequestKey = ""
        }
      }
      return checkpointSummary.value
    })()
    checkpointSummaryRequest = request
    return request
  }

  async function loadReplay(traceId?: string) {
    const target = (traceId ?? replayTraceId.value).trim()
    loadingReplay.value = true
    error.value = ""
    replayEvents.value = []
    replayTraceId.value = target
    try {
      if (!target) {
        error.value = "请先输入一条运行记录编号。"
        return
      }
      const response = await adminApi.replayRuntimeTrace(target)
      replayEvents.value = response?.events || []
      if (!replayEvents.value.length) {
        error.value = "没有找到这条运行记录，或者它不属于当前空间。"
      }
    } catch (caught: any) {
      error.value = getApiErrorMessage(caught, "运行记录没有加载出来，请确认编号后再试。")
    } finally {
      loadingReplay.value = false
    }
  }

  return {
    loadingToolSummary,
    loadingCheckpointSummary,
    loadingReplay,
    error,
    toolDecisionSummary,
    checkpointSummary,
    replayTraceId,
    replayEvents,
    toolFilters,
    toolMatrixRows,
    reasonMatrixRows,
    trendRows,
    loadToolDecisionSummary,
    loadCheckpointSummary,
    loadReplay,
  }
})

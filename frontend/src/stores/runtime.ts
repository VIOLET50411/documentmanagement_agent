import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { adminApi } from "@/api/admin"
import { getApiErrorMessage } from "@/utils/adminUi"

type GenericRecord = Record<string, any>

export const useRuntimeStore = defineStore("runtime", () => {
  const loadingToolSummary = ref(false)
  const loadingCheckpointSummary = ref(false)
  const loadingReplay = ref(false)
  const error = ref("")
  const toolDecisionSummary = ref<GenericRecord | null>(null)
  const checkpointSummary = ref<GenericRecord[]>([])
  const replayTraceId = ref("")
  const replayEvents = ref<GenericRecord[]>([])
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

  async function loadToolDecisionSummary() {
    if (loadingToolSummary.value) return

    loadingToolSummary.value = true
    error.value = ""
    try {
      toolDecisionSummary.value = await adminApi.getRuntimeToolDecisionSummary(toolFilters.value)
    } catch (caught: any) {
      error.value = getApiErrorMessage(caught, "运行过程的工具使用情况暂时没加载出来，请稍后再试。")
    } finally {
      loadingToolSummary.value = false
    }
  }

  async function loadCheckpointSummary(limit = 50) {
    if (loadingCheckpointSummary.value) return

    loadingCheckpointSummary.value = true
    error.value = ""
    try {
      const response = await adminApi.getRuntimeCheckpointSummary(limit)
      checkpointSummary.value = response?.items || []
    } catch (caught: any) {
      error.value = getApiErrorMessage(caught, "恢复点信息暂时没加载出来，请稍后再试。")
    } finally {
      loadingCheckpointSummary.value = false
    }
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

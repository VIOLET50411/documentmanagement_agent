import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { adminApi } from "@/api/admin"

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
    loadingToolSummary.value = true
    error.value = ""
    try {
      toolDecisionSummary.value = await adminApi.getRuntimeToolDecisionSummary(toolFilters.value)
    } catch (caught: any) {
      error.value = caught?.response?.data?.detail || "加载运行时工具治理统计失败。"
    } finally {
      loadingToolSummary.value = false
    }
  }

  async function loadCheckpointSummary(limit = 50) {
    loadingCheckpointSummary.value = true
    error.value = ""
    try {
      const response = await adminApi.getRuntimeCheckpointSummary(limit)
      checkpointSummary.value = response?.items || []
    } catch (caught: any) {
      error.value = caught?.response?.data?.detail || "加载运行时检查点摘要失败。"
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
        error.value = "请先输入 trace_id。"
        return
      }
      const response = await adminApi.replayRuntimeTrace(target)
      replayEvents.value = response?.events || []
      if (!replayEvents.value.length) {
        error.value = "没有找到对应运行轨迹，或该轨迹不属于当前租户。"
      }
    } catch (caught: any) {
      error.value = caught?.response?.data?.detail || "加载运行轨迹失败。"
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

import { computed, reactive } from "vue"
import { adminApi } from "@/api/admin"
import { getRecentHttpTraces } from "@/api/http"
import { useRuntimeStore } from "@/stores/runtime"
import { backendMonitorErrorLabel, getApiErrorMessage } from "@/utils/adminUi"

type GenericMap = Record<string, any>

export function useAdminBackends() {
  const runtimeStore = useRuntimeStore()
  const state = reactive({
    loading: false,
    error: "",
    backends: {} as GenericMap,
    retrievalMetrics: {} as GenericMap,
    requestMetrics: [] as GenericMap[],
    frontendHttpTraces: [] as GenericMap[],
    retrievalIntegrity: null as GenericMap | null,
    readiness: null as GenericMap | null,
    publicCorpusLatest: null as GenericMap | null,
    loadingPublicCorpusLatest: false,
    exportingPublicCorpus: false,
    publicCorpusForm: {
      dataset_name: "swu_public_docs",
      tenant_id: "public_cold_start",
      train_ratio: 0.9,
    },
    publicCorpusTaskId: "",
  })

  const backendCards = computed(() => [
    { label: "Elasticsearch", value: backendLabel(state.backends.elasticsearch, "documents", "份文档") },
    { label: "Milvus", value: backendLabel(state.backends.milvus, "entities", "条实体") },
    { label: "Neo4j", value: backendLabel(state.backends.neo4j, "relationships", "条关系") },
    { label: "Redis", value: state.backends.redis?.available ? "可用" : "不可用" },
    { label: "大模型", value: llmLabel(state.backends.llm) },
    { label: "ClamAV", value: clamavLabel(state.backends.clamav) },
  ])

  const retrievalMetricsRows = computed(() => {
    const rows = [] as GenericMap[]
    const raw = state.retrievalMetrics?.backends || {}
    for (const backend of ["es", "milvus", "graph"]) {
      const item = raw[backend]
      if (item) rows.push({ backend, ...item })
    }
    return rows
  })

  function backendLabel(item: GenericMap | null | undefined, key: string, suffix = "") {
    if (!item) return "未知"
    if (!item.available) return "不可用"
    return `${item[key] ?? 0}${suffix}`
  }

  function clamavLabel(item: GenericMap | null | undefined) {
    if (!item) return "未知"
    if (item.enabled === false) return "未启用"
    if (item.available) return "可用"
    return "降级运行中"
  }

  function llmLabel(item: GenericMap | null | undefined) {
    if (!item) return "未知"
    if (item.enabled === false) return "未启用"
    if (!item.available) return "不可用"
    if (item.model_pulled === false) return "模型尚未准备好"
    return "可用"
  }

  async function loadBackends() {
    if (state.loading) return

    state.loading = true
    state.error = ""
    try {
      const [backendRes, retrievalMetricsRes, readinessRes, requestMetricsRes] = await Promise.all([
        adminApi.getBackendStatus(),
        adminApi.getRetrievalMetrics(),
        adminApi.getPlatformReadiness(),
        adminApi.getRequestMetrics(8),
      ])
      state.backends = backendRes || {}
      state.retrievalMetrics = retrievalMetricsRes || {}
      state.readiness = readinessRes || null
      state.requestMetrics = requestMetricsRes?.items || []
      state.frontendHttpTraces = getRecentHttpTraces().slice(0, 12)
    } catch (err: any) {
      state.error = getApiErrorMessage(err, backendMonitorErrorLabel("system"))
    } finally {
      state.loading = false
    }
  }

  async function loadRetrievalIntegrity() {
    try {
      state.retrievalIntegrity = (await adminApi.getRetrievalIntegrity(12)) || null
    } catch (err: any) {
      state.error = getApiErrorMessage(err, backendMonitorErrorLabel("retrieval"))
    }
  }

  async function loadPublicCorpusLatest() {
    state.loadingPublicCorpusLatest = true
    state.error = ""
    try {
      state.publicCorpusLatest = await adminApi.getLatestPublicCorpusExport(
        state.publicCorpusForm.dataset_name,
        state.publicCorpusForm.tenant_id,
      )
    } catch (err: any) {
      state.error = getApiErrorMessage(err, backendMonitorErrorLabel("publicCorpusLoad"))
    } finally {
      state.loadingPublicCorpusLatest = false
    }
  }

  async function pollPublicCorpusTask() {
    if (!state.publicCorpusTaskId) return
    try {
      const payload = await adminApi.getPublicCorpusExportTask(state.publicCorpusTaskId, state.publicCorpusForm.tenant_id)
      const status = payload?.item?.status || ""
      if (status === "completed") {
        await loadPublicCorpusLatest()
        return
      }
      if (status === "failed" || status === "killed") {
        state.error = payload?.item?.error || backendMonitorErrorLabel("publicCorpusTask")
        return
      }
      window.setTimeout(() => {
        void pollPublicCorpusTask()
      }, 2500)
    } catch (err: any) {
      state.error = getApiErrorMessage(err, backendMonitorErrorLabel("publicCorpusPoll"))
    }
  }

  async function exportPublicCorpusAsync() {
    state.exportingPublicCorpus = true
    state.error = ""
    try {
      const task = await adminApi.exportPublicCorpusAsync(
        state.publicCorpusForm.dataset_name,
        state.publicCorpusForm.tenant_id,
        state.publicCorpusForm.train_ratio,
      )
      state.publicCorpusTaskId = task.task_id || ""
      await pollPublicCorpusTask()
    } catch (err: any) {
      state.error = getApiErrorMessage(err, backendMonitorErrorLabel("publicCorpusStart"))
    } finally {
      state.exportingPublicCorpus = false
    }
  }

  function downloadRuntimeToolSummary() {
    try {
      const blob = new Blob([JSON.stringify(runtimeStore.toolDecisionSummary || {}, null, 2)], {
        type: "application/json;charset=utf-8",
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = "runtime_tool_decision_summary.json"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch {
      state.error = backendMonitorErrorLabel("toolExport")
    }
  }

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  function formatPercent(value: number | null | undefined) {
    if (value === null || value === undefined) return "-"
    return `${(Number(value) * 100).toFixed(1)}%`
  }

  function backendNameLabel(value: string) {
    const map: Record<string, string> = {
      es: "Elasticsearch",
      milvus: "Milvus",
      graph: "Graph",
    }
    return map[value] || value
  }

  function requestPathLabel(value: string | null | undefined) {
    const normalized = String(value || "").trim()
    if (!normalized) return "-"
    return normalized.replace("/api/v1", "")
  }

  function frontendTraceStatusLabel(value?: number | null) {
    if (!value) return "失败"
    if (value >= 200 && value < 300) return `${value}`
    return `${value}`
  }

  return {
    state,
    backendCards,
    retrievalMetricsRows,
    loadBackends,
    loadRetrievalIntegrity,
    loadPublicCorpusLatest,
    exportPublicCorpusAsync,
    downloadRuntimeToolSummary,
    formatDate,
    formatPercent,
    backendNameLabel,
    requestPathLabel,
    frontendTraceStatusLabel,
  }
}

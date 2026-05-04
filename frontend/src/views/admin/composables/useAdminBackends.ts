import { reactive, computed } from "vue"
import { adminApi } from "@/api/admin"
import { useRuntimeStore } from "@/stores/runtime"

type GenericMap = Record<string, any>

export function useAdminBackends() {
  const runtimeStore = useRuntimeStore()
  const state = reactive({
    loading: false,
    error: "",
    backends: {} as GenericMap,
    retrievalMetrics: {} as GenericMap,
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
    { label: "Elasticsearch", value: backendLabel(state.backends.elasticsearch, "documents") },
    { label: "Milvus", value: backendLabel(state.backends.milvus, "entities") },
    { label: "Neo4j", value: backendLabel(state.backends.neo4j, "relationships") },
    { label: "Redis", value: state.backends.redis?.available ? "在线" : "离线" },
    { label: "LLM", value: llmLabel(state.backends.llm) },
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

  function backendLabel(item: GenericMap | null | undefined, key: string) {
    if (!item) return "未知"
    if (!item.available) return "离线"
    return `${item[key] ?? 0}`
  }

  function clamavLabel(item: GenericMap | null | undefined) {
    if (!item) return "未知"
    if (item.enabled === false) return "未启用"
    if (item.available) return "在线"
    return "降级"
  }

  function llmLabel(item: GenericMap | null | undefined) {
    if (!item) return "未知"
    if (item.enabled === false) return "未启用"
    if (!item.available) return "离线"
    if (item.model_pulled === false) return "模型未拉取"
    return "在线"
  }

  async function loadBackends() {
    state.loading = true
    state.error = ""
    try {
      const [backendRes, retrievalMetricsRes, readinessRes, retrievalIntegrityRes] = await Promise.all([
        adminApi.getBackendStatus(),
        adminApi.getRetrievalMetrics(),
        adminApi.getPlatformReadiness(),
        adminApi.getRetrievalIntegrity(12),
      ])
      state.backends = backendRes || {}
      state.retrievalMetrics = retrievalMetricsRes || {}
      state.readiness = readinessRes || null
      state.retrievalIntegrity = retrievalIntegrityRes || null
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "加载后端状态失败。"
    } finally {
      state.loading = false
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
      state.error = err?.response?.data?.detail || "加载公开语料导出摘要失败。"
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
        state.error = payload?.item?.error || "公开语料导出失败。"
        return
      }
      window.setTimeout(() => {
        void pollPublicCorpusTask()
      }, 2500)
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "轮询公开语料导出任务失败。"
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
      state.error = err?.response?.data?.detail || "提交公开语料导出任务失败。"
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
      state.error = "导出工具治理统计失败。"
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

  return {
    state,
    backendCards,
    retrievalMetricsRows,
    loadBackends,
    loadPublicCorpusLatest,
    exportPublicCorpusAsync,
    downloadRuntimeToolSummary,
    formatDate,
    formatPercent
  }
}

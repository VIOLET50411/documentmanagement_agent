import { computed, reactive } from "vue"
import { adminApi } from "@/api/admin"
import { useRuntimeStore } from "@/stores/runtime"

type GenericMap = Record<string, any>

export function useAdminDashboard() {
  const runtimeStore = useRuntimeStore()
  const dashboard = reactive({
    activeTab: "overview",
    loading: false,
    error: "",
    analytics: {} as GenericMap,
    users: [] as GenericMap[],
    invitations: [] as GenericMap[],
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
    securityEvents: [] as GenericMap[],
    securityTotal: 0,
    securityPage: 0,
    securityPageSize: 20,
    loadingSecurity: false,
    securityAlerts: [] as GenericMap[],
    securityFilters: {
      severity: "",
      action: "",
      result: "",
    },
    evaluation: {} as GenericMap,
    runtimeMetrics: null as GenericMap | null,
    runtimeHistory: [] as GenericMap[],
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
    evaluationRunning: false,
    inviting: false,
    inviteMessage: "",
    inviteForm: {
      email: "",
      role: "EMPLOYEE",
      department: "",
      level: 2,
      expires_hours: 72,
    },
    tabs: [
      { key: "overview", label: "总览" },
      { key: "users", label: "用户管理" },
      { key: "pipeline", label: "处理管线" },
      { key: "backends", label: "检索后端" },
      { key: "inspect", label: "运行检查" },
      { key: "security", label: "安全审计" },
      { key: "evaluation", label: "评估报告" },
    ],
  })

  const statCards = computed(() => [
    { label: "总查询数", value: dashboard.analytics.total_queries ?? 0 },
    { label: "文档总数", value: dashboard.analytics.total_documents ?? 0 },
    { label: "已完成文档", value: dashboard.analytics.ready_documents ?? 0 },
    { label: "处理中", value: dashboard.analytics.processing_documents ?? 0 },
    { label: "失败文档", value: dashboard.analytics.failed_documents ?? 0 },
    { label: "平均满意度", value: dashboard.analytics.avg_satisfaction ?? "-" },
    { label: "缓存命中率", value: `${((dashboard.analytics.cache_hit_rate ?? 0) * 100).toFixed(1)}%` },
    { label: "安全事件数", value: dashboard.analytics.security_event_count ?? 0 },
  ])

  const pipelineCards = computed(() => [
    { label: "活动任务", value: dashboard.pipeline.active ?? 0 },
    { label: "排队任务", value: dashboard.pipeline.queued ?? 0 },
    { label: "失败任务", value: dashboard.pipeline.failed ?? 0 },
    { label: "完成任务", value: dashboard.pipeline.completed ?? 0 },
  ])

  const backendCards = computed(() => [
    { label: "Elasticsearch", value: backendLabel(dashboard.backends.elasticsearch, "documents") },
    { label: "Milvus", value: backendLabel(dashboard.backends.milvus, "entities") },
    { label: "Neo4j", value: backendLabel(dashboard.backends.neo4j, "relationships") },
    { label: "Redis", value: dashboard.backends.redis?.available ? "在线" : "离线" },
    { label: "LLM", value: llmLabel(dashboard.backends.llm) },
    { label: "ClamAV", value: clamavLabel(dashboard.backends.clamav) },
  ])

  const retrievalMetricsRows = computed(() => {
    const rows = [] as GenericMap[]
    const raw = dashboard.retrievalMetrics?.backends || {}
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

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  function formatPercent(value: number | null | undefined) {
    if (value === null || value === undefined) return "-"
    return `${(Number(value) * 100).toFixed(1)}%`
  }

  async function loadDashboard() {
    dashboard.loading = true
    dashboard.error = ""
    try {
      const [
        analyticsRes,
        usersRes,
        invitationsRes,
        pipelineRes,
        pipelineJobsRes,
        pipelineSummaryRes,
        securityRes,
        securityAlertRes,
        evaluationRes,
        runtimeMetricsRes,
        runtimeHistoryRes,
        backendRes,
        retrievalMetricsRes,
        readinessRes,
        retrievalIntegrityRes,
        publicCorpusLatestRes,
      ] = await Promise.all([
        adminApi.getAnalytics(),
        adminApi.listUsers(),
        adminApi.listInvitations({ limit: 20, offset: 0 }),
        adminApi.getPipelineStatus(),
        adminApi.getPipelineJobs({
          limit: dashboard.pipelinePageSize,
          offset: dashboard.pipelinePage * dashboard.pipelinePageSize,
          status: dashboard.pipelineFilterStatus || undefined,
        }),
        adminApi.getPipelineFailureSummary(20),
        adminApi.getSecurityEvents({
          limit: dashboard.securityPageSize,
          offset: dashboard.securityPage * dashboard.securityPageSize,
        }),
        adminApi.getSecurityAlerts({ limit: 20, offset: 0 }),
        adminApi.getLatestEvaluation(),
        adminApi.getRuntimeEvaluationMetrics(),
        adminApi.getRuntimeEvaluationHistory(30),
        adminApi.getBackendStatus(),
        adminApi.getRetrievalMetrics(),
        adminApi.getPlatformReadiness(),
        adminApi.getRetrievalIntegrity(12),
        adminApi.getLatestPublicCorpusExport(dashboard.publicCorpusForm.dataset_name, dashboard.publicCorpusForm.tenant_id),
      ])

      dashboard.analytics = analyticsRes
      dashboard.users = usersRes
      dashboard.invitations = invitationsRes
      dashboard.pipeline = pipelineRes
      dashboard.pipelineJobs = pipelineJobsRes.jobs || []
      dashboard.pipelineTotal = pipelineJobsRes.total || 0
      dashboard.pipelineFailureSummary = pipelineSummaryRes.items || []
      dashboard.securityEvents = securityRes.events || []
      dashboard.securityTotal = securityRes.total || 0
      dashboard.securityAlerts = securityAlertRes.alerts || []
      dashboard.evaluation = evaluationRes || {}
      dashboard.runtimeMetrics = runtimeMetricsRes || null
      dashboard.runtimeHistory = runtimeHistoryRes?.items || []
      dashboard.backends = backendRes || {}
      dashboard.retrievalMetrics = retrievalMetricsRes || {}
      dashboard.readiness = readinessRes || null
      dashboard.retrievalIntegrity = retrievalIntegrityRes || null
      dashboard.publicCorpusLatest = publicCorpusLatestRes || null
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "加载管理台数据失败。"
    } finally {
      dashboard.loading = false
    }
  }

  async function loadDashboardLite() {
    const [analyticsRes, pipelineRes] = await Promise.all([adminApi.getAnalytics(), adminApi.getPipelineStatus()])
    dashboard.analytics = analyticsRes
    dashboard.pipeline = pipelineRes
  }

  async function loadPipelineJobs() {
    dashboard.loadingPipeline = true
    dashboard.error = ""
    try {
      const [response, summary] = await Promise.all([
        adminApi.getPipelineJobs({
          limit: dashboard.pipelinePageSize,
          offset: dashboard.pipelinePage * dashboard.pipelinePageSize,
          status: dashboard.pipelineFilterStatus || undefined,
        }),
        adminApi.getPipelineFailureSummary(20),
      ])
      dashboard.pipelineJobs = response.jobs || []
      dashboard.pipelineTotal = response.total || 0
      dashboard.pipelineFailureSummary = summary.items || []
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "加载任务失败。"
    } finally {
      dashboard.loadingPipeline = false
    }
  }

  async function applyPipelineFilter() {
    dashboard.pipelinePage = 0
    await loadPipelineJobs()
  }

  async function changePipelinePage(delta: number) {
    const nextPage = dashboard.pipelinePage + delta
    if (nextPage < 0) return
    dashboard.pipelinePage = nextPage
    await loadPipelineJobs()
  }

  async function retryPipelineJob(job: GenericMap) {
    dashboard.error = ""
    try {
      await adminApi.retryPipelineJob(job.doc_id)
      await Promise.all([loadPipelineJobs(), loadDashboardLite()])
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "重试任务失败。"
    }
  }

  async function retryFailedJobs() {
    dashboard.retryingFailed = true
    dashboard.error = ""
    try {
      await adminApi.retryFailedPipelineJobs(20, true)
      await Promise.all([loadPipelineJobs(), loadDashboardLite()])
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "批量重试失败。"
    } finally {
      dashboard.retryingFailed = false
    }
  }

  async function retryBySignature(signature: string) {
    dashboard.retryingSignature = signature
    dashboard.error = ""
    try {
      await adminApi.retryPipelineBySignature(signature, 20)
      await Promise.all([loadPipelineJobs(), loadDashboardLite()])
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "按错误类型重试失败。"
    } finally {
      dashboard.retryingSignature = ""
    }
  }

  async function loadPublicCorpusLatest() {
    dashboard.loadingPublicCorpusLatest = true
    dashboard.error = ""
    try {
      dashboard.publicCorpusLatest = await adminApi.getLatestPublicCorpusExport(
        dashboard.publicCorpusForm.dataset_name,
        dashboard.publicCorpusForm.tenant_id,
      )
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "加载公开语料导出摘要失败。"
    } finally {
      dashboard.loadingPublicCorpusLatest = false
    }
  }

  async function exportPublicCorpusAsync() {
    dashboard.exportingPublicCorpus = true
    dashboard.error = ""
    try {
      const task = await adminApi.exportPublicCorpusAsync(
        dashboard.publicCorpusForm.dataset_name,
        dashboard.publicCorpusForm.tenant_id,
        dashboard.publicCorpusForm.train_ratio,
      )
      dashboard.publicCorpusTaskId = task.task_id || ""
      await pollPublicCorpusTask()
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "提交公开语料导出任务失败。"
    } finally {
      dashboard.exportingPublicCorpus = false
    }
  }

  async function pollPublicCorpusTask() {
    if (!dashboard.publicCorpusTaskId) return
    try {
      const payload = await adminApi.getPublicCorpusExportTask(dashboard.publicCorpusTaskId, dashboard.publicCorpusForm.tenant_id)
      const status = payload?.item?.status || ""
      if (status === "completed") {
        await loadPublicCorpusLatest()
        return
      }
      if (status === "failed" || status === "killed") {
        dashboard.error = payload?.item?.error || "公开语料导出失败。"
        return
      }
      window.setTimeout(() => {
        void pollPublicCorpusTask()
      }, 2500)
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "轮询公开语料导出任务失败。"
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
      dashboard.error = "导出工具治理统计失败。"
    }
  }

  async function runEvaluation() {
    dashboard.evaluationRunning = true
    dashboard.error = ""
    try {
      await adminApi.runEvaluation(100)
      const [evalRes, runtimeRes, runtimeHistoryRes] = await Promise.all([
        adminApi.getLatestEvaluation(),
        adminApi.getRuntimeEvaluationMetrics(),
        adminApi.getRuntimeEvaluationHistory(30),
      ])
      dashboard.evaluation = evalRes
      dashboard.runtimeMetrics = runtimeRes
      dashboard.runtimeHistory = runtimeHistoryRes?.items || []
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "运行评估失败。"
    } finally {
      dashboard.evaluationRunning = false
    }
  }

  async function downloadRuntimeMetrics(format: "csv" | "json") {
    try {
      const content = await adminApi.exportRuntimeEvaluationMetrics(format, 100)
      const mime = format === "json" ? "application/json;charset=utf-8" : "text/csv;charset=utf-8"
      const blob = new Blob([typeof content === "string" ? content : JSON.stringify(content, null, 2)], { type: mime })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `runtime_metrics.${format}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "导出运行时指标失败。"
    }
  }

  function roleToLevel(role: string) {
    const map: Record<string, number> = { VIEWER: 1, EMPLOYEE: 2, MANAGER: 5, ADMIN: 9 }
    return map[role] || 2
  }

  async function inviteUser() {
    dashboard.inviting = true
    dashboard.error = ""
    dashboard.inviteMessage = ""
    try {
      const payload = {
        email: dashboard.inviteForm.email,
        role: dashboard.inviteForm.role,
        department: dashboard.inviteForm.department || null,
        level: roleToLevel(dashboard.inviteForm.role),
        expires_hours: 72,
      }
      const result = await adminApi.inviteUser(payload)
      dashboard.inviteMessage = `邀请已发送，令牌：${result.token}`
      dashboard.inviteForm.email = ""
      dashboard.inviteForm.department = ""
      await loadDashboard()
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "发送邀请失败。"
    } finally {
      dashboard.inviting = false
    }
  }

  async function resendInvitation(invitation: GenericMap) {
    dashboard.error = ""
    try {
      const result = await adminApi.resendInvitation(invitation.invitation_id, 72)
      dashboard.inviteMessage = `已重新发送邀请：${result.email}`
      await loadDashboard()
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "重发邀请失败。"
    }
  }

  async function revokeInvitation(invitation: GenericMap) {
    dashboard.error = ""
    try {
      await adminApi.revokeInvitation(invitation.invitation_id)
      dashboard.inviteMessage = `已撤销邀请：${invitation.email}`
      await loadDashboard()
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "撤销邀请失败。"
    }
  }

  async function loadSecurityEvents(resetPage = true) {
    dashboard.loadingSecurity = true
    dashboard.error = ""
    try {
      const offset = resetPage ? 0 : dashboard.securityPage * dashboard.securityPageSize
      if (resetPage) dashboard.securityPage = 0
      const response = await adminApi.getSecurityEvents({
        limit: dashboard.securityPageSize,
        offset,
        severity: dashboard.securityFilters.severity || undefined,
        action: dashboard.securityFilters.action || undefined,
        result: dashboard.securityFilters.result || undefined,
      })
      dashboard.securityEvents = response.events || []
      dashboard.securityTotal = response.total || 0
      const alerts = await adminApi.getSecurityAlerts({ limit: 20, offset: 0 })
      dashboard.securityAlerts = alerts.alerts || []
    } catch (err: any) {
      dashboard.error = err?.response?.data?.detail || "加载安全事件失败。"
    } finally {
      dashboard.loadingSecurity = false
    }
  }

  async function changeSecurityPage(delta: number) {
    const nextPage = dashboard.securityPage + delta
    if (nextPage < 0) return
    dashboard.securityPage = nextPage
    await loadSecurityEvents(false)
  }

  function invitationStatusLabel(status: string) {
    const map: Record<string, string> = {
      pending: "待使用",
      used: "已使用",
      expired: "已过期",
      revoked: "已撤销",
    }
    return map[status] || status || "未知"
  }

  return {
    dashboard,
    statCards,
    pipelineCards,
    backendCards,
    retrievalMetricsRows,
    formatDate,
    formatPercent,
    invitationStatusLabel,
    loadDashboard,
    loadPipelineJobs,
    applyPipelineFilter,
    changePipelinePage,
    retryPipelineJob,
    retryFailedJobs,
    retryBySignature,
    loadPublicCorpusLatest,
    exportPublicCorpusAsync,
    downloadRuntimeToolSummary,
    runEvaluation,
    downloadRuntimeMetrics,
    inviteUser,
    resendInvitation,
    revokeInvitation,
    loadSecurityEvents,
    changeSecurityPage,
  }
}

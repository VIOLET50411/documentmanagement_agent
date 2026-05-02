import { apiGet, apiPost } from "./http"

type QueryParams = Record<string, string | number | boolean | null | undefined>

export const adminApi = {
  listUsers() {
    return apiGet("/admin/users")
  },

  inviteUser(payload: Record<string, unknown>) {
    return apiPost("/auth/invite", payload)
  },

  listInvitations(params: QueryParams = {}) {
    return apiGet("/auth/invitations", { params })
  },

  resendInvitation(invitationId: string, expiresHours = 72) {
    return apiPost(`/auth/invite/${invitationId}/resend`, null, { params: { expires_hours: expiresHours } })
  },

  revokeInvitation(invitationId: string) {
    return apiPost(`/auth/invite/${invitationId}/revoke`)
  },

  getAnalytics() {
    return apiGet("/admin/analytics/overview")
  },

  getPipelineStatus() {
    return apiGet("/admin/pipeline/status")
  },

  getPipelineJobs(params: QueryParams = {}) {
    return apiGet("/admin/pipeline/jobs", { params: { limit: 20, offset: 0, ...params } })
  },

  retryPipelineJob(docId: string) {
    return apiPost(`/admin/pipeline/${docId}/retry`)
  },

  retryFailedPipelineJobs(limit = 20, includePartialFailed = true) {
    return apiPost("/admin/pipeline/retry-failed", null, {
      params: { limit, include_partial_failed: includePartialFailed },
    })
  },

  getPipelineFailureSummary(limit = 20) {
    return apiGet("/admin/pipeline/failure-summary", { params: { limit } })
  },

  retryPipelineBySignature(signature: string, limit = 20) {
    return apiPost("/admin/pipeline/retry-by-signature", null, { params: { signature, limit } })
  },

  getSecurityEvents(params: QueryParams = {}) {
    return apiGet("/admin/security/events", { params: { limit: 50, offset: 0, ...params } })
  },

  getSecurityAlerts(params: QueryParams = {}) {
    return apiGet("/admin/security/alerts", { params: { limit: 50, offset: 0, ...params } })
  },

  getBackendStatus() {
    return apiGet("/admin/system/backends")
  },

  getLLMDomainConfig() {
    return apiGet("/admin/llm/domain-config")
  },

  getSecurityPolicy() {
    return apiGet("/admin/system/security-policy")
  },

  getMobileAuthStatus() {
    return apiGet("/admin/system/mobile-auth")
  },

  getPushNotificationStatus() {
    return apiGet("/admin/system/push-notifications")
  },

  getRetrievalMetrics() {
    return apiGet("/admin/system/retrieval-metrics")
  },

  getPlatformReadiness() {
    return apiGet("/admin/system/readiness")
  },

  getRetrievalIntegrity(sampleSize = 12) {
    return apiGet("/admin/system/retrieval-integrity", { params: { sample_size: sampleSize } })
  },

  runEvaluation(sampleLimit = 100) {
    return apiPost("/admin/evaluation/run", null, { params: { sample_limit: sampleLimit } })
  },

  getLatestEvaluation() {
    return apiGet("/admin/evaluation/latest")
  },

  getRuntimeEvaluationMetrics() {
    return apiGet("/admin/evaluation/runtime-metrics")
  },

  getRuntimeEvaluationHistory(limit = 30) {
    return apiGet("/admin/evaluation/runtime-metrics/history", { params: { limit } })
  },

  exportRuntimeEvaluationMetrics(format: "csv" | "json" = "csv", limit = 100) {
    return apiGet("/admin/evaluation/runtime-metrics/export", { params: { format, limit } })
  },

  getRuntimeToolDecisionSummary(params: QueryParams = {}) {
    const payload = { limit: 1000, since_hours: 24, ...params }
    return apiGet("/admin/runtime/tool-decisions/summary", { params: payload })
  },

  getRuntimeCheckpointSummary(limit = 50) {
    return apiGet("/admin/runtime/checkpoints/summary", { params: { limit } })
  },

  replayRuntimeTrace(traceId: string) {
    return apiPost("/admin/runtime/replay", null, { params: { trace_id: traceId } })
  },

  getRuntimeTasks(limit = 20, offset = 0) {
    return apiGet("/admin/runtime/tasks", { params: { limit, offset } })
  },

  getRuntimeMetrics(limit = 200) {
    return apiGet("/admin/runtime/metrics", { params: { limit } })
  },

  getLatestPublicCorpusExport(datasetName = "swu_public_docs", tenantId = "public_cold_start") {
    return apiGet("/admin/llm/public-corpus/latest", { params: { dataset_name: datasetName, tenant_id: tenantId } })
  },

  exportPublicCorpusAsync(datasetName = "swu_public_docs", tenantId = "public_cold_start", trainRatio = 0.9) {
    return apiPost("/admin/llm/public-corpus/export-async", null, {
      params: { dataset_name: datasetName, tenant_id: tenantId, train_ratio: trainRatio },
    })
  },

  getPublicCorpusExportTask(taskId: string, tenantId = "public_cold_start") {
    return apiGet(`/admin/llm/public-corpus/tasks/${taskId}`, { params: { tenant_id: tenantId } })
  },

  getLLMTrainingJobs(limit = 20, tenantId?: string) {
    return apiGet("/admin/llm/training/jobs", { params: { limit, tenant_id: tenantId } })
  },

  getLLMTrainingSummary(limit = 100, tenantId?: string) {
    return apiGet("/admin/llm/training/summary", { params: { limit, tenant_id: tenantId } })
  },

  getLLMDeploymentSummary(limit = 20, tenantId?: string) {
    return apiGet("/admin/llm/deployment/summary", { params: { limit, tenant_id: tenantId } })
  },
}

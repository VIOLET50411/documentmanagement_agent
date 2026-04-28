<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <h1>系统管理</h1>
        <p class="page-subtitle">查看租户用户、处理队列、检索后端、安全事件与评估结果。</p>
      </div>
      <button class="refresh-btn" @click="loadDashboard" :disabled="dashboard.loading">
        {{ dashboard.loading ? "刷新中..." : "刷新数据" }}
      </button>
    </header>

    <div class="admin-tabs">
      <button v-for="tab in dashboard.tabs" :key="tab.key" class="tab-btn" :class="{ active: dashboard.activeTab === tab.key }" @click="dashboard.activeTab = tab.key">
        {{ tab.label }}
      </button>
    </div>

    <div v-if="dashboard.error" class="error-banner">{{ dashboard.error }}</div>

    <AdminOverviewPanel
      v-if="dashboard.activeTab === 'overview'"
      :dashboard="dashboard"
      :stat-cards="statCards"
      :format-date="formatDate"
    />
    <UserManagement
      v-else-if="dashboard.activeTab === 'users'"
      :dashboard="dashboard"
      :invite-user="inviteUser"
      :resend-invitation="resendInvitation"
      :revoke-invitation="revokeInvitation"
      :invitation-status-label="invitationStatusLabel"
      :format-date="formatDate"
    />
    <IngestionDashboard
      v-else-if="dashboard.activeTab === 'pipeline'"
      :dashboard="dashboard"
      :pipeline-cards="pipelineCards"
      :load-pipeline-jobs="loadPipelineJobs"
      :apply-pipeline-filter="applyPipelineFilter"
      :change-pipeline-page="changePipelinePage"
      :retry-pipeline-job="retryPipelineJob"
      :retry-failed-jobs="retryFailedJobs"
      :retry-by-signature="retryBySignature"
      :format-date="formatDate"
    />
    <SystemMonitor
      v-else-if="dashboard.activeTab === 'backends'"
      :dashboard="dashboard"
      :backend-cards="backendCards"
      :retrieval-metrics-rows="retrievalMetricsRows"
      :runtime-tool-matrix-rows="runtimeToolMatrixRows"
      :runtime-reason-matrix-rows="runtimeReasonMatrixRows"
      :runtime-trend-rows="runtimeTrendRows"
      :format-date="formatDate"
      :format-percent="formatPercent"
      :load-runtime-tool-decision-summary="loadRuntimeToolDecisionSummary"
      :load-runtime-checkpoint-summary="loadRuntimeCheckpointSummary"
      :download-runtime-tool-summary="downloadRuntimeToolSummary"
    />
    <SecurityAudit
      v-else-if="dashboard.activeTab === 'security'"
      :dashboard="dashboard"
      :load-security-events="loadSecurityEvents"
      :change-security-page="changeSecurityPage"
      :format-date="formatDate"
    />
    <RuntimeEvaluation
      v-else
      :dashboard="dashboard"
      :format-percent="formatPercent"
      :run-evaluation="runEvaluation"
      :download-runtime-metrics="downloadRuntimeMetrics"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue"
import AdminOverviewPanel from "./AdminOverviewPanel.vue"
import IngestionDashboard from "./IngestionDashboard.vue"
import RuntimeEvaluation from "./RuntimeEvaluation.vue"
import SecurityAudit from "./SecurityAudit.vue"
import SystemMonitor from "./SystemMonitor.vue"
import UserManagement from "./UserManagement.vue"
import { useAdminDashboard } from "./useAdminDashboard"

const {
  dashboard,
  statCards,
  pipelineCards,
  backendCards,
  retrievalMetricsRows,
  runtimeToolMatrixRows,
  runtimeReasonMatrixRows,
  runtimeTrendRows,
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
  loadRuntimeToolDecisionSummary,
  loadRuntimeCheckpointSummary,
  downloadRuntimeToolSummary,
  runEvaluation,
  downloadRuntimeMetrics,
  inviteUser,
  resendInvitation,
  revokeInvitation,
  loadSecurityEvents,
  changeSecurityPage,
} = useAdminDashboard()

onMounted(loadDashboard)
</script>

<style scoped>
.admin-page {
  padding: 0 12px 12px;
  overflow-y: auto;
  height: 100%;
}

.page-header {
  max-width: 1240px;
  margin: 0 auto 18px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-4);
}

.page-header h1 {
  font-size: clamp(1.8rem, 3vw, 2.6rem);
  line-height: 1.08;
}

.page-subtitle {
  color: var(--text-secondary);
  font-size: 1rem;
  margin-top: 10px;
}

.refresh-btn {
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  border-radius: 999px;
  padding: 12px 16px;
  cursor: pointer;
  transition: transform var(--transition-fast), background-color var(--transition-fast), border-color var(--transition-fast);
}

.refresh-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  background: var(--bg-surface-hover);
}

.refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.admin-tabs {
  max-width: 1240px;
  margin: 0 auto var(--space-6);
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tab-btn {
  padding: 10px 14px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-family);
}

.tab-btn:hover {
  color: var(--text-primary);
  background: var(--bg-surface-hover);
}

.tab-btn.active {
  color: var(--text-primary);
  background: var(--text-primary);
  border-color: var(--text-primary);
  box-shadow: 0 16px 28px rgba(36, 31, 23, 0.14);
}

.theme-dark .tab-btn.active {
  color: #17130f;
  background: #f5eee3;
  border-color: #f5eee3;
}

.error-banner {
  max-width: 1240px;
  margin: 0 auto var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-radius: 18px;
  background: rgba(197, 86, 67, 0.12);
  color: var(--color-danger);
}
:deep(.stats-grid) { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-4); }
:deep(.panel-grid) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); margin-top: var(--space-6); }
:deep(.pipeline-grid), :deep(.evaluation-grid) { grid-template-columns: repeat(4, minmax(0, 1fr)); }
:deep(.stat-card) { display: flex; flex-direction: column; align-items: center; padding: var(--space-6); text-align: center; }
:deep(.stat-card.compact) { padding: var(--space-4); }
:deep(.stat-value) { font-size: var(--text-3xl); font-weight: 700; color: var(--color-primary); }
:deep(.stat-value.small) { font-size: var(--text-xl); }
:deep(.stat-label) { font-size: var(--text-sm); color: var(--text-secondary); margin-top: var(--space-1); }
:deep(.section-card) { margin-top: var(--space-6); padding: var(--space-6); }
:deep(.section-card h2) { margin-bottom: var(--space-4); }
:deep(.sub-section-title) { margin-top: var(--space-6); }
:deep(.evaluation-header) { display: flex; justify-content: space-between; gap: var(--space-3); align-items: center; margin-bottom: var(--space-4); }
:deep(.list) { display: flex; flex-direction: column; gap: var(--space-3); }
:deep(.list-item) { display: flex; justify-content: space-between; gap: var(--space-4); padding-bottom: var(--space-3); border-bottom: 1px solid var(--border-color); }
:deep(.list-item.stacked) { flex-direction: column; gap: var(--space-1); }
:deep(.event-topline) { display: flex; justify-content: space-between; gap: var(--space-3); }
:deep(.list-title) { color: var(--text-primary); }
:deep(.list-meta), :deep(.list-note), :deep(.empty-text), :deep(.report-meta) { color: var(--text-secondary); }
:deep(.severity) { text-transform: uppercase; font-size: 12px; letter-spacing: 0.04em; }
:deep(.severity.high) { color: #d64541; }
:deep(.severity.medium) { color: #c87d0a; }
:deep(.severity.low) { color: #3b82f6; }
:deep(.data-table) { width: 100%; border-collapse: collapse; }
:deep(.data-table th), :deep(.data-table td) { padding: var(--space-3); border-bottom: 1px solid var(--border-color); text-align: left; vertical-align: top; }
:deep(.action-group) { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; }
:deep(.filters-grid) { display: grid; grid-template-columns: 1fr 2fr 1fr auto; gap: var(--space-2); margin-bottom: var(--space-4); }
:deep(.pagination-row) { display: flex; justify-content: space-between; align-items: center; margin-top: var(--space-4); gap: var(--space-2); }
:deep(.report-box) { margin-top: var(--space-4); background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: var(--space-4); white-space: pre-wrap; word-break: break-word; }
:deep(.invite-form) { display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: var(--space-2); margin-bottom: var(--space-4); }
@media (max-width: 1200px) {
  :deep(.stats-grid),
  :deep(.pipeline-grid),
  :deep(.evaluation-grid) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .admin-page { padding: var(--space-4); }
  :deep(.panel-grid),
  :deep(.stats-grid),
  :deep(.pipeline-grid),
  :deep(.evaluation-grid),
  :deep(.filters-grid),
  :deep(.invite-form) { grid-template-columns: 1fr; }
  :deep(.pagination-row),
  .page-header { flex-direction: column; }
}
</style>

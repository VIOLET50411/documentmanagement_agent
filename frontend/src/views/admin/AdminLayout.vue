<template>
  <div class="admin-page">
    <div class="admin-tabs">
      <button v-for="tab in tabs" :key="tab.key" class="tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        {{ tab.label }}
      </button>
    </div>

    <AdminOverviewPanel v-if="activeTab === 'overview'" />
    <UserManagement v-else-if="activeTab === 'users'" />
    <IngestionDashboard v-else-if="activeTab === 'pipeline'" />
    <SystemMonitor v-else-if="activeTab === 'backends'" />
    <RetrievalDebug v-else-if="activeTab === 'retrieval'" />
    <RuntimeInspect v-else-if="activeTab === 'inspect'" :format-date="formatDate" />
    <SecurityAudit v-else-if="activeTab === 'security'" />
    <RuntimeEvaluation v-else />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import AdminOverviewPanel from "./AdminOverviewPanel.vue"
import IngestionDashboard from "./IngestionDashboard.vue"
import RetrievalDebug from "./RetrievalDebug.vue"
import RuntimeEvaluation from "./RuntimeEvaluation.vue"
import RuntimeInspect from "./RuntimeInspect.vue"
import SecurityAudit from "./SecurityAudit.vue"
import SystemMonitor from "./SystemMonitor.vue"
import UserManagement from "./UserManagement.vue"

const route = useRoute()
const router = useRouter()
const activeTab = ref("overview")

const tabs = [
  { key: "overview", label: "总览" },
  { key: "users", label: "用户管理" },
  { key: "pipeline", label: "数据管线" },
  { key: "backends", label: "后端状态" },
  { key: "retrieval", label: "检索调试" },
  { key: "inspect", label: "运行排查" },
  { key: "security", label: "安全审计" },
  { key: "evaluation", label: "评测报告" },
]

onMounted(() => {
  const tab = route.query.tab
  if (typeof tab === "string" && tabs.some((item) => item.key === tab)) {
    activeTab.value = tab
  }
})

watch(
  () => route.query.tab,
  (newTab) => {
    if (typeof newTab === "string" && tabs.some((item) => item.key === newTab)) {
      activeTab.value = newTab
    }
  },
)

function switchTab(key: string) {
  activeTab.value = key
  router.push({ query: { ...route.query, tab: key } })
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
</script>

<style scoped>
.admin-page {
  padding: 0 12px 12px;
  overflow-y: auto;
  height: 100%;
}

.admin-tabs {
  max-width: 1240px;
  margin: 0 auto var(--space-6);
  display: inline-flex;
  gap: 4px;
  flex-wrap: wrap;
  background: var(--bg-surface-strong);
  padding: 4px;
  border-radius: 12px;
}

.tab-btn {
  padding: 8px 16px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-family);
}

.tab-btn:hover {
  color: var(--text-primary);
}

.tab-btn.active {
  color: var(--text-primary) !important;
  background: var(--bg-surface);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.theme-dark .tab-btn.active {
  color: var(--text-primary) !important;
  background: var(--bg-surface);
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

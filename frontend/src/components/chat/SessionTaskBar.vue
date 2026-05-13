<template>
  <section v-if="visible" class="taskbar card-shell">
    <div class="taskbar-head">
      <div>
        <p class="taskbar-kicker">运行任务</p>
        <h3>当前平台异步任务</h3>
      </div>
      <button class="taskbar-refresh" type="button" :disabled="loading" @click="loadTasks">
        {{ loading ? "刷新中..." : "刷新" }}
      </button>
    </div>

    <div v-if="error" class="taskbar-error">{{ error }}</div>

    <div v-if="items.length" class="taskbar-list">
      <article v-for="item in items" :key="item.task_id" class="task-card">
        <div class="task-card-head">
          <span class="task-type">{{ taskTypeLabel(item.type) }}</span>
          <span class="task-status" :data-status="item.status">{{ statusLabel(item.status) }}</span>
        </div>
        <p class="task-desc">{{ item.description || "暂无任务说明" }}</p>
        <div class="task-meta">
          <span>阶段：{{ item.stage || "-" }}</span>
          <span>更新时间：{{ formatTime(item.updated_at || item.end_time || item.start_time) }}</span>
        </div>
      </article>
    </div>

    <div v-else-if="!loading" class="taskbar-empty">当前没有需要重点关注的运行任务。</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { adminApi } from "@/api/admin"
import { useAuthStore } from "@/stores/auth"

type RuntimeTask = {
  task_id: string
  type: string
  status: string
  description?: string
  stage?: string | null
  updated_at?: string | null
  end_time?: string | null
  start_time?: string | null
}

const authStore = useAuthStore()
const loading = ref(false)
const error = ref("")
const items = ref<RuntimeTask[]>([])

const visible = computed(() => authStore.user?.role === "ADMIN")

let refreshTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  if (!visible.value) return
  void loadTasks()
  refreshTimer = setInterval(() => {
    void loadTasks()
  }, 15000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})

async function loadTasks() {
  if (!visible.value) return
  loading.value = true
  error.value = ""
  try {
    const response = await adminApi.getRuntimeTasks(12, 0)
    const rawItems = Array.isArray(response?.items) ? response.items : []
    const ranked = [...rawItems].sort((a, b) => scoreTask(b) - scoreTask(a))
    items.value = ranked.slice(0, 4)
  } catch (caught: any) {
    error.value = normalizeTaskError(caught)
  } finally {
    loading.value = false
  }
}

function normalizeTaskError(caught: any) {
  const detail = String(caught?.response?.data?.detail || caught?.message || "").trim()
  if (!detail) return "运行任务加载失败，请稍后再试。"
  if (/401|403|forbidden|unauthorized/i.test(detail)) {
    return "当前账号没有查看运行任务的权限。"
  }
  if (/timeout|timed out/i.test(detail)) {
    return "运行任务加载超时，请稍后刷新。"
  }
  return `运行任务加载失败：${detail}`
}

function scoreTask(item: RuntimeTask) {
  const statusScore: Record<string, number> = {
    running: 100,
    pending: 80,
    failed: 70,
    killed: 40,
    completed: 10,
  }
  const timeValue = new Date(item.updated_at || item.end_time || item.start_time || 0).getTime() || 0
  return (statusScore[item.status] || 0) * 1_000_000_000_000 + timeValue
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "待执行",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
    killed: "已终止",
  }
  return labels[status] || status
}

function taskTypeLabel(type: string) {
  const labels: Record<string, string> = {
    ingestion: "文档入库",
    evaluation: "评估任务",
    maintenance: "维护任务",
    llm_training: "模型训练",
    training: "模型训练",
    generic: "通用任务",
  }
  return labels[type] || type
}

function formatTime(value?: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`
}
</script>

<style scoped>
.card-shell {
  border: 1px solid var(--border-color);
  border-radius: 24px;
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent);
  box-shadow: var(--shadow-sm);
}

.taskbar {
  padding: 18px 20px;
}

.taskbar-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.taskbar-kicker {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.taskbar-head h3 {
  margin: 8px 0 0;
  font-size: 1.05rem;
  color: var(--text-primary);
}

.taskbar-refresh {
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.38);
  color: var(--text-secondary);
  padding: 8px 12px;
}

.taskbar-error,
.taskbar-empty {
  margin-top: 14px;
  color: var(--text-secondary);
  font-size: 14px;
}

.taskbar-list {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.task-card {
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.34);
}

.task-card-head,
.task-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.task-type,
.task-status,
.task-meta {
  font-size: 13px;
}

.task-type {
  color: var(--text-secondary);
}

.task-status {
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.52);
  color: var(--text-secondary);
}

.task-status[data-status="running"] {
  color: #166534;
  background: rgba(34, 197, 94, 0.16);
}

.task-status[data-status="failed"] {
  color: #b42318;
  background: rgba(217, 45, 32, 0.14);
}

.task-status[data-status="pending"] {
  color: #8a5b13;
  background: rgba(245, 158, 11, 0.16);
}

.task-desc {
  margin: 10px 0;
  color: var(--text-primary);
  line-height: 1.6;
}

.task-meta {
  color: var(--text-tertiary);
  flex-wrap: wrap;
}
</style>

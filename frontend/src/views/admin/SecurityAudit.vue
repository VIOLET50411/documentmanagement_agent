<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <h2>安全记录</h2>

      <StatusMessage v-if="state.error" tone="error" :message="state.error" />

      <div class="filters-grid">
        <select v-model="state.securityFilters.severity" class="input">
          <option value="">全部风险级别</option>
          <option value="low">低风险</option>
          <option value="medium">中风险</option>
          <option value="high">高风险</option>
        </select>
        <input v-model="state.securityFilters.action" class="input" type="text" placeholder="按事件类型筛选，例如 输入内容被拦截" />
        <select v-model="state.securityFilters.result" class="input">
          <option value="">全部处理结果</option>
          <option value="ok">已放行</option>
          <option value="blocked">已拦截</option>
          <option value="error">执行出错</option>
        </select>
      </div>

      <ul v-if="state.securityEvents.length" class="list">
        <li v-for="(event, index) in state.securityEvents" :key="index" class="list-item stacked">
          <div class="event-topline">
            <span class="list-title">{{ eventTypeLabel(event.event_type) }}</span>
            <span class="severity" :class="event.severity?.toLowerCase()">{{ severityLabel(event.severity) }}</span>
          </div>
          <span class="list-note">{{ event.message }}</span>
          <span class="list-meta">处理结果：{{ resultLabel(event.result) }} | {{ formatDate(event.timestamp) }}</span>
        </li>
      </ul>
      <EmptyState v-else title="当前还没有安全记录。" description="这通常说明近期没有触发明显的安全策略事件。" />

      <div class="pagination-row">
        <span class="list-meta">共 {{ state.securityTotal }} 条，当前第 {{ state.securityPage + 1 }} 页</span>
        <div class="action-group">
          <button class="btn btn-ghost" :disabled="state.securityPage === 0 || state.loadingSecurity" @click="changeSecurityPage(-1)">上一页</button>
          <button class="btn btn-ghost" :disabled="(state.securityPage + 1) * state.securityPageSize >= state.securityTotal || state.loadingSecurity" @click="changeSecurityPage(1)">下一页</button>
        </div>
      </div>

      <h2 class="sub-section-title">重点提醒</h2>
      <ul v-if="state.securityAlerts.length" class="list">
        <li v-for="(event, index) in state.securityAlerts" :key="`alert-${index}`" class="list-item stacked">
          <div class="event-topline">
            <span class="list-title">{{ eventTypeLabel(event.event_type) }}</span>
            <span class="severity" :class="event.severity?.toLowerCase()">{{ severityLabel(event.severity) }}</span>
          </div>
          <span class="list-note">{{ event.message }}</span>
          <span class="list-meta">处理结果：{{ resultLabel(event.result) }} | {{ formatDate(event.timestamp) }}</span>
        </li>
      </ul>
      <EmptyState v-else title="当前没有需要额外关注的安全提醒。" description="高风险、已拦截或执行出错的事件会优先显示在这里。" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue"
import EmptyState from "@/components/common/EmptyState.vue"
import StatusMessage from "@/components/common/StatusMessage.vue"
import { useAdminSecurity } from "./composables/useAdminSecurity"

const { state, loadSecurityEvents, changeSecurityPage, formatDate, severityLabel, resultLabel, eventTypeLabel } = useAdminSecurity()

let timer: number
let visibilityHandler: (() => void) | null = null

function stopPolling() {
  if (timer) {
    window.clearInterval(timer)
    timer = 0
  }
}

function startPolling() {
  stopPolling()
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return
  timer = window.setInterval(() => {
    loadSecurityEvents(false)
  }, 10000)
}

onMounted(() => {
  loadSecurityEvents()
  startPolling()
  visibilityHandler = () => {
    if (document.visibilityState === "visible") {
      void loadSecurityEvents(false)
      startPolling()
      return
    }
    stopPolling()
  }
  document.addEventListener("visibilitychange", visibilityHandler)
})

watch(
  () => state.securityFilters,
  () => {
    loadSecurityEvents(true)
  },
  { deep: true },
)

onUnmounted(() => {
  stopPolling()
  if (visibilityHandler) {
    document.removeEventListener("visibilitychange", visibilityHandler)
  }
})
</script>

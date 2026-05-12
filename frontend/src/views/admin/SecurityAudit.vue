<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <h2>安全事件</h2>
      <div class="filters-grid">
        <select v-model="state.securityFilters.severity" class="input">
          <option value="">全部风险级别</option>
          <option value="low">LOW</option>
          <option value="medium">MEDIUM</option>
          <option value="high">HIGH</option>
        </select>
        <input v-model="state.securityFilters.action" class="input" type="text" placeholder="动作类型，例如 input_blocked" />
        <select v-model="state.securityFilters.result" class="input">
          <option value="">全部结果</option>
          <option value="ok">OK</option>
          <option value="blocked">BLOCKED</option>
          <option value="error">ERROR</option>
        </select>
      </div>
      <ul v-if="state.securityEvents.length" class="list">
        <li v-for="(event, index) in state.securityEvents" :key="index" class="list-item stacked">
          <div class="event-topline">
            <span class="list-title">{{ event.event_type }}</span>
            <span class="severity" :class="event.severity?.toLowerCase()">{{ event.severity }}</span>
          </div>
          <span class="list-note">{{ event.message }}</span>
          <span class="list-meta">{{ formatDate(event.timestamp) }}</span>
        </li>
      </ul>
      <p v-else class="empty-text">暂无安全事件。</p>
      <div class="pagination-row">
        <span class="list-meta">共 {{ state.securityTotal }} 条，当前第 {{ state.securityPage + 1 }} 页</span>
        <div class="action-group">
          <button class="btn btn-ghost" :disabled="state.securityPage === 0 || state.loadingSecurity" @click="changeSecurityPage(-1)">上一页</button>
          <button
            class="btn btn-ghost"
            :disabled="(state.securityPage + 1) * state.securityPageSize >= state.securityTotal || state.loadingSecurity"
            @click="changeSecurityPage(1)"
          >
            下一页
          </button>
        </div>
      </div>
      <h2 class="sub-section-title">告警流（高风险 / 拦截 / 错误）</h2>
      <ul v-if="state.securityAlerts.length" class="list">
        <li v-for="(event, index) in state.securityAlerts" :key="`alert-${index}`" class="list-item stacked">
          <div class="event-topline">
            <span class="list-title">{{ event.event_type }}</span>
            <span class="severity" :class="event.severity?.toLowerCase()">{{ event.severity }}</span>
          </div>
          <span class="list-note">{{ event.message }}</span>
          <span class="list-meta">{{ formatDate(event.timestamp) }}</span>
        </li>
      </ul>
      <p v-else class="empty-text">暂无告警事件。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue"
import { useAdminSecurity } from "./composables/useAdminSecurity"

const { state, loadSecurityEvents, changeSecurityPage, formatDate } = useAdminSecurity()

let timer: number

onMounted(() => {
  loadSecurityEvents()
  timer = window.setInterval(() => {
    loadSecurityEvents(false)
  }, 10000)
})

watch(
  () => state.securityFilters,
  () => {
    loadSecurityEvents(true)
  },
  { deep: true },
)

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

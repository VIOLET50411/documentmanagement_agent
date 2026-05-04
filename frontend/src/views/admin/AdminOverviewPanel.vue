<template>
  <div class="tab-content animate-fade-in">
    <div class="stats-grid">
      <div 
        v-for="item in statCards" 
        :key="item.label" 
        class="stat-card card" 
        :class="{ clickable: !!item.tab }"
        @click="item.tab && $router.push({ query: { tab: item.tab } })"
      >
        <span class="stat-value">{{ item.value }}</span>
        <span class="stat-label">{{ item.label }}</span>
      </div>
    </div>
    <div class="panel-grid">
      <section class="card section-card">
        <h2>高频查询</h2>
        <ul v-if="state.analytics.top_queries?.length" class="list">
          <li v-for="item in state.analytics.top_queries" :key="item.query" class="list-item">
            <span class="list-title">{{ item.query }}</span>
            <span class="list-meta">{{ item.count }} 次</span>
          </li>
        </ul>
        <p v-else class="empty-text">暂无查询数据。</p>
      </section>

      <section class="card section-card">
        <h2>最近反馈</h2>
        <ul v-if="state.analytics.recent_feedback?.length" class="list">
          <li v-for="(item, index) in state.analytics.recent_feedback" :key="index" class="list-item stacked">
            <span class="list-title">评分：{{ item.rating }}</span>
            <span class="list-meta">{{ formatDate(item.created_at) }}</span>
            <span class="list-note">{{ item.correction || "无补充说明" }}</span>
          </li>
        </ul>
        <p v-else class="empty-text">暂无反馈数据。</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAdminOverview } from './composables/useAdminOverview'

const {
  state,
  statCards,
  loadOverview,
  formatDate
} = useAdminOverview()

onMounted(() => {
  loadOverview()
})
</script>

<style scoped>
.clickable {
  cursor: pointer;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}
.clickable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
</style>

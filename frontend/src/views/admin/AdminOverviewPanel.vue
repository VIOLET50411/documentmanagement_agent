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

      <section class="card section-card">
        <h2>文档状态分布</h2>
        <div v-if="state.analytics.document_status_distribution?.length" class="bar-list">
          <div v-for="item in state.analytics.document_status_distribution" :key="item.status" class="bar-row">
            <div class="bar-head">
              <span class="list-title">{{ item.status }}</span>
              <span class="list-meta">{{ item.count }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill primary" :style="{ width: calcBarWidth(item.count, maxDocumentStatusCount) }"></div>
            </div>
          </div>
        </div>
        <p v-else class="empty-text">暂无文档状态数据。</p>
      </section>

      <section class="card section-card">
        <h2>用户角色分布</h2>
        <div v-if="state.analytics.role_distribution?.length" class="bar-list">
          <div v-for="item in state.analytics.role_distribution" :key="item.role" class="bar-row">
            <div class="bar-head">
              <span class="list-title">{{ item.role }}</span>
              <span class="list-meta">{{ item.count }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill accent" :style="{ width: calcBarWidth(item.count, maxRoleCount) }"></div>
            </div>
          </div>
        </div>
        <p v-else class="empty-text">暂无角色分布数据。</p>
      </section>

      <section class="card section-card">
        <h2>近 7 日查询趋势</h2>
        <div v-if="state.analytics.query_trend_7d?.length" class="trend-grid">
          <div v-for="item in state.analytics.query_trend_7d" :key="item.day" class="trend-col">
            <div class="trend-bar-wrap">
              <div class="trend-bar" :style="{ height: calcTrendHeight(item.count, maxTrendCount) }"></div>
            </div>
            <strong>{{ item.count }}</strong>
            <span>{{ item.day.slice(5) }}</span>
          </div>
        </div>
        <p v-else class="empty-text">暂无趋势数据。</p>
      </section>

      <section class="card section-card">
        <h2>反馈评分分布</h2>
        <div v-if="state.analytics.feedback_distribution?.length" class="bar-list">
          <div v-for="item in state.analytics.feedback_distribution" :key="item.rating" class="bar-row">
            <div class="bar-head">
              <span class="list-title">{{ item.rating }} 分</span>
              <span class="list-meta">{{ item.count }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill warning" :style="{ width: calcBarWidth(item.count, maxFeedbackCount) }"></div>
            </div>
          </div>
        </div>
        <p v-else class="empty-text">暂无反馈分布数据。</p>
      </section>

      <section class="card section-card">
        <h2>平台运营动作</h2>
        <div class="action-group ops-actions">
          <button class="btn btn-primary" :disabled="state.runningAction === 'reindex'" @click="runOpsAction('reindex')">
            {{ state.runningAction === 'reindex' ? '重建中...' : '重建索引' }}
          </button>
          <button class="btn btn-ghost" :disabled="state.runningAction === 'retry_failed'" @click="runOpsAction('retry_failed')">
            {{ state.runningAction === 'retry_failed' ? '处理中...' : '批量重试失败任务' }}
          </button>
          <button class="btn btn-ghost" :disabled="state.runningAction === 'evaluation'" @click="runOpsAction('evaluation')">
            {{ state.runningAction === 'evaluation' ? '启动中...' : '启动运行评估' }}
          </button>
          <button class="btn btn-ghost" :disabled="state.runningAction === 'refresh_health'" @click="runOpsAction('refresh_health')">
            {{ state.runningAction === 'refresh_health' ? '刷新中...' : '刷新平台体检' }}
          </button>
        </div>
        <p v-if="state.actionMessage" class="report-meta success">{{ state.actionMessage }}</p>
        <p v-if="state.error" class="report-meta error">{{ state.error }}</p>
        <ul class="list compact-list">
          <li class="list-item">
            <span class="list-title">平台就绪度</span>
            <span class="list-meta">{{ state.readiness?.status || state.readiness?.overall_status || '未知' }}</span>
          </li>
          <li class="list-item">
            <span class="list-title">检索健康</span>
            <span class="list-meta">{{ state.retrievalIntegrity?.healthy ? 'healthy' : 'needs attention' }}</span>
          </li>
          <li class="list-item">
            <span class="list-title">Milvus 样本召回</span>
            <span class="list-meta">{{ state.retrievalIntegrity?.stats?.milvus_sample_recall ?? '-' }}</span>
          </li>
          <li class="list-item">
            <span class="list-title">ES 文档量</span>
            <span class="list-meta">{{ state.retrievalIntegrity?.stats?.es_documents ?? '-' }}</span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useAdminOverview } from './composables/useAdminOverview'

const {
  state,
  statCards,
  loadOverview,
  runOpsAction,
  formatDate
} = useAdminOverview()

const maxDocumentStatusCount = computed(() => Math.max(...(state.analytics.document_status_distribution || []).map((item: any) => Number(item.count || 0)), 1))
const maxRoleCount = computed(() => Math.max(...(state.analytics.role_distribution || []).map((item: any) => Number(item.count || 0)), 1))
const maxTrendCount = computed(() => Math.max(...(state.analytics.query_trend_7d || []).map((item: any) => Number(item.count || 0)), 1))
const maxFeedbackCount = computed(() => Math.max(...(state.analytics.feedback_distribution || []).map((item: any) => Number(item.count || 0)), 1))

onMounted(() => {
  loadOverview()
})

function calcBarWidth(value: number, maxValue: number) {
  return `${Math.max(8, Math.round((Number(value || 0) / Math.max(maxValue, 1)) * 100))}%`
}

function calcTrendHeight(value: number, maxValue: number) {
  return `${Math.max(16, Math.round((Number(value || 0) / Math.max(maxValue, 1)) * 140))}px`
}
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

.ops-actions {
  margin-bottom: 12px;
}

.compact-list {
  margin-top: 10px;
}

.success {
  color: #18794e;
}

.error {
  color: #c0392b;
}

.bar-list {
  display: grid;
  gap: 12px;
}

.bar-row {
  display: grid;
  gap: 6px;
}

.bar-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.bar-track {
  width: 100%;
  height: 10px;
  border-radius: 999px;
  background: var(--bg-surface-strong);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
}

.bar-fill.primary {
  background: #4f7cff;
}

.bar-fill.accent {
  background: #10b981;
}

.bar-fill.warning {
  background: #f59e0b;
}

.trend-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 12px;
  align-items: end;
  min-height: 220px;
}

.trend-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.trend-bar-wrap {
  width: 100%;
  min-height: 150px;
  display: flex;
  align-items: flex-end;
}

.trend-bar {
  width: 100%;
  border-radius: 10px 10px 0 0;
  background: linear-gradient(180deg, #4f7cff 0%, #7aa2ff 100%);
}
</style>

<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="evaluation-header">
        <h2>评估报告</h2>
        <div class="action-group">
          <button class="refresh-btn" @click="runEvaluation" :disabled="state.evaluating">
            {{ state.evaluating ? "运行中..." : "重新评估" }}
          </button>
          <button class="btn btn-ghost" @click="downloadRuntimeMetrics">导出数据</button>
        </div>
      </div>

      <div v-if="state.runtimeMetricsSummary" class="stats-grid evaluation-grid">
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.retrieval_hit_rate) }}</span>
          <span class="stat-label">检索命中率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.citation_coverage) }}</span>
          <span class="stat-label">引用覆盖率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.access_control_correctness) }}</span>
          <span class="stat-label">访问控制正确率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.cache_hit_rate) }}</span>
          <span class="stat-label">缓存命中率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.ingestion_success_rate) }}</span>
          <span class="stat-label">入库成功率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ state.runtimeMetricsSummary.sse_first_event_latency_p95_ms ?? "-" }}</span>
          <span class="stat-label">SSE 首事件 P95(ms)</span>
        </div>
      </div>

      <div v-if="state.evaluationLatest?.metrics" class="stats-grid evaluation-grid">
        <div v-for="(value, key) in state.evaluationLatest.metrics" :key="key" class="stat-card card compact">
          <span class="stat-value small">{{ value }}</span>
          <span class="stat-label">{{ key }}</span>
        </div>
      </div>

      <h2 class="sub-section-title">运行时指标历史</h2>
      <table v-if="state.runtimeMetricsHistory.length" class="data-table">
        <thead>
          <tr>
            <th>检索命中率</th>
            <th>引用覆盖率</th>
            <th>缓存命中率</th>
            <th>入库成功率</th>
            <th>SSE P95(ms)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, index) in state.runtimeMetricsHistory" :key="index">
            <td>{{ formatPercent(item.retrieval_hit_rate) }}</td>
            <td>{{ formatPercent(item.citation_coverage) }}</td>
            <td>{{ formatPercent(item.cache_hit_rate) }}</td>
            <td>{{ formatPercent(item.ingestion_success_rate) }}</td>
            <td>{{ item.sse_first_event_latency_p95_ms ?? "-" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无运行时指标历史。</p>

      <p v-if="state.evaluationLatest?.dataset_size" class="report-meta">样本数：{{ state.evaluationLatest.dataset_size }}</p>
      <pre v-if="state.evaluationLatest?.markdown" class="report-box">{{ state.evaluationLatest.markdown }}</pre>
      <p v-else class="empty-text">暂无评估报告。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAdminEvaluation } from './composables/useAdminEvaluation'

const {
  state,
  loadEvaluation,
  runEvaluation,
  downloadRuntimeMetrics,
  formatPercent
} = useAdminEvaluation()

onMounted(() => {
  loadEvaluation()
})
</script>

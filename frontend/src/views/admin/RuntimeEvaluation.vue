<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="evaluation-header">
        <h2>评估报告</h2>
        <div class="action-group">
          <button class="refresh-btn" @click="runEvaluation" :disabled="dashboard.evaluationRunning">{{ dashboard.evaluationRunning ? "运行中..." : "重新评估" }}</button>
          <button class="btn btn-ghost" @click="downloadRuntimeMetrics('csv')">导出CSV</button>
          <button class="btn btn-ghost" @click="downloadRuntimeMetrics('json')">导出JSON</button>
        </div>
      </div>
      <div v-if="dashboard.runtimeMetrics" class="stats-grid evaluation-grid">
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(dashboard.runtimeMetrics.retrieval_hit_rate) }}</span>
          <span class="stat-label">检索命中率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(dashboard.runtimeMetrics.citation_coverage) }}</span>
          <span class="stat-label">引用覆盖率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(dashboard.runtimeMetrics.access_control_correctness) }}</span>
          <span class="stat-label">访问控制正确率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(dashboard.runtimeMetrics.cache_hit_rate) }}</span>
          <span class="stat-label">缓存命中率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(dashboard.runtimeMetrics.ingestion_success_rate) }}</span>
          <span class="stat-label">摄取成功率</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.runtimeMetrics.sse_first_event_latency_p95_ms ?? "-" }}</span>
          <span class="stat-label">SSE首事件P95(ms)</span>
        </div>
      </div>
      <div v-if="dashboard.evaluation.metrics" class="stats-grid evaluation-grid">
        <div v-for="(value, key) in dashboard.evaluation.metrics" :key="key" class="stat-card card compact">
          <span class="stat-value small">{{ value }}</span>
          <span class="stat-label">{{ key }}</span>
        </div>
      </div>
      <h2 class="sub-section-title">运行时指标历史</h2>
      <table v-if="dashboard.runtimeHistory.length" class="data-table">
        <thead><tr><th>检索命中率</th><th>引用覆盖率</th><th>缓存命中率</th><th>摄取成功率</th><th>SSE P95(ms)</th></tr></thead>
        <tbody>
          <tr v-for="(item, index) in dashboard.runtimeHistory" :key="index">
            <td>{{ formatPercent(item.retrieval_hit_rate) }}</td>
            <td>{{ formatPercent(item.citation_coverage) }}</td>
            <td>{{ formatPercent(item.cache_hit_rate) }}</td>
            <td>{{ formatPercent(item.ingestion_success_rate) }}</td>
            <td>{{ item.sse_first_event_latency_p95_ms ?? "-" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无运行时指标历史。</p>
      <p v-if="dashboard.evaluation.dataset_size" class="report-meta">样本数：{{ dashboard.evaluation.dataset_size }}</p>
      <pre v-if="dashboard.evaluation.markdown" class="report-box">{{ dashboard.evaluation.markdown }}</pre>
      <p v-else class="empty-text">暂无评估报告。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  dashboard: Record<string, any>
  formatPercent: (value?: number | null) => string
  runEvaluation: () => Promise<void>
  downloadRuntimeMetrics: (format: "csv" | "json") => Promise<void>
}>()
</script>

<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="evaluation-header">
        <div>
          <h2>评测报告</h2>
          <p class="report-meta">最近一次评测时间：{{ formatDate(state.evaluationLatest?.generated_at) }}</p>
        </div>
        <div class="action-group">
          <button class="refresh-btn" @click="runEvaluation" :disabled="state.evaluating">
            {{ state.evaluating ? "运行中..." : "重新评测" }}
          </button>
          <button class="btn btn-ghost" @click="downloadRuntimeMetrics">导出运行指标</button>
        </div>
      </div>

      <div v-if="state.evalError" class="error-inline">{{ state.evalError }}</div>

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

      <h2 class="sub-section-title">评测指标</h2>
      <div v-if="metricCards.length" class="stats-grid evaluation-grid">
        <div v-for="item in metricCards" :key="item.key" class="stat-card card compact">
          <span class="stat-value small">{{ item.value }}</span>
          <span class="stat-label">{{ item.label }}</span>
        </div>
      </div>
      <p v-else class="empty-text">暂无评测指标。</p>

      <h2 class="sub-section-title">数据集概览</h2>
      <div v-if="datasetSummary" class="panel-grid summary-grid">
        <div class="card compact-panel">
          <div class="panel-title">样本规模</div>
          <div class="summary-list">
            <div class="summary-item"><span>样本数</span><strong>{{ datasetSummary.dataset_size ?? 0 }}</strong></div>
            <div class="summary-item"><span>文档数</span><strong>{{ datasetSummary.unique_doc_count ?? 0 }}</strong></div>
            <div class="summary-item"><span>Grounded 样本</span><strong>{{ datasetSummary.grounded_sample_count ?? 0 }}</strong></div>
            <div class="summary-item"><span>平均上下文长度</span><strong>{{ datasetSummary.avg_context_length ?? 0 }}</strong></div>
          </div>
        </div>

        <div class="card compact-panel">
          <div class="panel-title">题型覆盖</div>
          <div v-if="taskTypeEntries.length" class="tag-list">
            <span v-for="item in taskTypeEntries" :key="item.key" class="summary-tag">{{ item.key }} x {{ item.value }}</span>
          </div>
          <p v-else class="empty-text">本次评测尚未记录题型统计。</p>
        </div>

        <div class="card compact-panel">
          <div class="panel-title">难度分布</div>
          <div v-if="difficultyEntries.length" class="tag-list">
            <span v-for="item in difficultyEntries" :key="item.key" class="summary-tag">{{ item.key }} x {{ item.value }}</span>
          </div>
          <p v-else class="empty-text">本次评测尚未记录难度分布。</p>
        </div>

        <div class="card compact-panel">
          <div class="panel-title">门禁状态</div>
          <div class="gate-status" :data-passed="state.evaluationLatest?.gate?.passed ? 'yes' : 'no'">
            {{ state.evaluationLatest?.gate?.passed ? "已通过" : "未通过" }}
          </div>
          <ul v-if="gateFailures.length" class="gate-list">
            <li v-for="failure in gateFailures" :key="failure.metric">
              {{ failure.metric }}: {{ failure.actual }} / {{ failure.threshold }}
            </li>
          </ul>
          <p v-else class="empty-text">当前没有门禁失败项。</p>
        </div>
      </div>
      <p v-else class="empty-text">暂无数据集摘要。</p>

      <h2 class="sub-section-title">手工评测样本</h2>
      <div class="panel-grid summary-grid">
        <div class="card compact-panel">
          <div class="panel-title">样本沉淀</div>
          <div class="summary-list">
            <div class="summary-item"><span>手工样本总数</span><strong>{{ manualSampleTotal }}</strong></div>
            <div class="summary-item"><span>本次参与评测</span><strong>{{ manualSampleUsed }}</strong></div>
            <div class="summary-item"><span>最近新增</span><strong>{{ formatDate(latestManualSampleAt) }}</strong></div>
          </div>
          <p v-if="state.evaluationDatasetSamplesPath" class="panel-path">{{ state.evaluationDatasetSamplesPath }}</p>
        </div>

        <div class="card compact-panel wide-panel">
          <div class="panel-title">最近样本</div>
          <div v-if="state.evaluationDatasetSamples.length" class="manual-sample-list">
            <article v-for="(item, index) in state.evaluationDatasetSamples" :key="`${item.question}-${index}`" class="manual-sample-card">
              <div class="manual-sample-head">
                <strong>{{ item.question || "未命名问题" }}</strong>
                <span class="history-badge" :data-passed="isManualSampleUsed(item) ? 'yes' : 'no'">
                  {{ isManualSampleUsed(item) ? "已参与本次评测" : "尚未参与本次评测" }}
                </span>
              </div>
              <p class="manual-answer">{{ item.reference || item.answer || "-" }}</p>
              <div class="manual-meta">
                <span>{{ item.task_type || "manual_debug" }}</span>
                <span>{{ item.difficulty || "manual" }}</span>
                <span>{{ formatDate(item.created_at) }}</span>
              </div>
            </article>
          </div>
          <p v-else class="empty-text">还没有手工评测样本。</p>
        </div>
      </div>

      <h2 class="sub-section-title">最近趋势</h2>
      <div v-if="historyCards.length" class="history-list">
        <div v-for="item in historyCards" :key="item.generated_at || item.dataset_size" class="history-item">
          <div class="history-topline">
            <strong>{{ formatDate(item.generated_at) }}</strong>
            <span class="history-badge" :data-passed="item.gate?.passed ? 'yes' : 'no'">
              {{ item.gate?.passed ? "通过" : "失败" }}
            </span>
          </div>
          <div class="history-meta">
            样本数 {{ item.dataset_size ?? 0 }} / faithfulness {{ item.metrics?.faithfulness ?? "-" }} / answer_relevancy
            {{ item.metrics?.answer_relevancy ?? "-" }}
          </div>
        </div>
      </div>
      <p v-else class="empty-text">暂无评测历史。</p>

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

      <h2 class="sub-section-title">原始报告</h2>
      <pre v-if="state.evaluationLatest?.markdown" class="report-box">{{ state.evaluationLatest.markdown }}</pre>
      <p v-else class="empty-text">暂无评测报告。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from "vue"
import { useAdminEvaluation } from "./composables/useAdminEvaluation"

const { state, loadEvaluation, runEvaluation, downloadRuntimeMetrics, formatPercent, formatDate } = useAdminEvaluation()

const datasetSummary = computed(() => state.evaluationLatest?.generated_from?.dataset_summary || null)

const metricCards = computed(() =>
  Object.entries(state.evaluationLatest?.metrics || {})
    .filter(([key]) => key !== "_meta")
    .map(([key, value]) => ({
      key,
      label: key,
      value,
    })),
)

const difficultyEntries = computed(() =>
  Object.entries(datasetSummary.value?.difficulty_counts || {}).map(([key, value]) => ({ key, value })),
)

const taskTypeEntries = computed(() =>
  Object.entries(datasetSummary.value?.task_type_counts || {}).map(([key, value]) => ({ key, value })),
)

const gateFailures = computed(() => state.evaluationLatest?.gate?.failures || [])
const historyCards = computed(() => state.evaluationHistory || [])
const manualSampleTotal = computed(
  () => state.evaluationLatest?.generated_from?.manual_sample_count_total ?? state.evaluationDatasetSamplesTotal ?? 0,
)
const manualSampleUsed = computed(() => state.evaluationLatest?.generated_from?.manual_sample_count_used ?? 0)
const latestManualSampleAt = computed(() => state.evaluationDatasetSamples[0]?.created_at || null)

function isManualSampleUsed(sample: Record<string, any>) {
  const used = Number(manualSampleUsed.value || 0)
  if (used <= 0) return false
  const signature = `${sample.question || ""}||${sample.reference || sample.answer || ""}`
  const activeDataset = state.evaluationDatasetSamples.slice(0, used)
  return activeDataset.some((item) => `${item.question || ""}||${item.reference || item.answer || ""}` === signature)
}

onMounted(() => {
  loadEvaluation()
})
</script>

<style scoped>
.summary-grid {
  align-items: stretch;
}

.compact-panel {
  padding: 16px;
}

.wide-panel {
  grid-column: span 2;
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.summary-list {
  display: grid;
  gap: 10px;
}

.summary-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  color: var(--text-secondary);
}

.summary-item strong {
  color: var(--text-primary);
}

.panel-path {
  margin-top: 12px;
  color: var(--text-tertiary);
  font-size: 12px;
  word-break: break-word;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.summary-tag {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--bg-surface-strong);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.gate-status {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  background: rgba(214, 69, 65, 0.12);
  color: #d64541;
}

.gate-status[data-passed="yes"] {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
}

.gate-list {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--text-secondary);
}

.manual-sample-list,
.history-list {
  display: grid;
  gap: 12px;
}

.manual-sample-card,
.history-item {
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-surface);
}

.manual-sample-head,
.history-topline {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.manual-answer,
.history-meta,
.manual-meta {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.manual-answer {
  white-space: pre-wrap;
  word-break: break-word;
}

.manual-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.history-badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(214, 69, 65, 0.12);
  color: #d64541;
  font-size: 12px;
  font-weight: 700;
}

.history-badge[data-passed="yes"] {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
}

.error-inline {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(214, 69, 65, 0.12);
  color: #d64541;
}

@media (max-width: 900px) {
  .wide-panel {
    grid-column: span 1;
  }

  .manual-sample-head,
  .history-topline {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>

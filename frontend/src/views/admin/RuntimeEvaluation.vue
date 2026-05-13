<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="evaluation-header">
        <div>
          <h2>问答效果检查</h2>
          <p class="report-meta">最近一次检查时间：{{ formatDate(state.evaluationLatest?.generated_at) }}</p>
        </div>
        <div class="action-group">
          <button class="refresh-btn" @click="runEvaluation" :disabled="state.evaluating">
            {{ state.evaluating ? "检查中..." : "重新检查" }}
          </button>
          <button class="btn btn-ghost" @click="downloadRuntimeMetrics">导出运行记录</button>
        </div>
      </div>

      <StatusMessage
        v-if="state.error"
        tone="error"
        title="检查数据没有加载出来"
        :message="state.error"
        dismissible
        action-label="重新加载"
        @dismiss="state.error = ''"
        @action="loadEvaluation"
      />
      <StatusMessage
        v-if="state.evalError"
        tone="error"
        title="这次检查没有顺利完成"
        :message="state.evalError"
        dismissible
        action-label="重新发起检查"
        @dismiss="state.evalError = ''"
        @action="runEvaluation"
      />

      <div class="card compact-panel run-config-panel">
        <div class="panel-title">本次怎么检查</div>
        <div class="run-config-grid">
          <label class="config-field">
            <span>总共抽多少条样本</span>
            <input v-model.number="state.evaluationRunConfig.sampleLimit" class="input compact-field" type="number" min="1" />
          </label>
          <label class="config-field">
            <span>手工样本占多少</span>
            <input v-model.number="manualRatioPercent" class="input compact-field" type="number" min="0" max="100" step="10" />
          </label>
          <label class="config-toggle">
            <input v-model="state.evaluationRunConfig.prioritizeAllManualSamples" type="checkbox" />
            <span>尽量把手工样本都带上</span>
          </label>
        </div>
        <p class="config-hint">
          按现在的设置，系统会优先放入 {{ manualTargetCount }} 条手工样本。
          <span v-if="state.evaluationRunConfig.prioritizeAllManualSamples">如果手工样本太多，会放宽总量，尽量把它们都带上。</span>
        </p>
      </div>

      <div v-if="state.runtimeMetricsSummary" class="stats-grid evaluation-grid">
        <div class="stat-card card compact"><span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.retrieval_hit_rate) }}</span><span class="stat-label">能不能找到资料</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.citation_coverage) }}</span><span class="stat-label">回答有没有带出处</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.access_control_correctness) }}</span><span class="stat-label">权限判断对不对</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.cache_hit_rate) }}</span><span class="stat-label">缓存有没有帮上忙</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ formatPercent(state.runtimeMetricsSummary.ingestion_success_rate) }}</span><span class="stat-label">资料入库是否顺利</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.runtimeMetricsSummary.sse_first_event_latency_p95_ms ?? "-" }}</span><span class="stat-label">首条响应耗时 P95(ms)</span></div>
      </div>

      <h2 class="sub-section-title">本次结果</h2>
      <div v-if="metricCards.length" class="stats-grid evaluation-grid">
        <div v-for="item in metricCards" :key="item.key" class="stat-card card compact">
          <span class="stat-value small">{{ item.value }}</span>
          <span class="stat-label">{{ item.label }}</span>
        </div>
      </div>
      <p v-else class="empty-text">还没有可展示的检查结果。</p>

      <h2 class="sub-section-title">这次抽样情况</h2>
      <div v-if="datasetSummary" class="panel-grid summary-grid">
        <div class="card compact-panel">
          <div class="panel-title">抽样规模</div>
          <div class="summary-list">
            <div class="summary-item"><span>样本数</span><strong>{{ datasetSummary.dataset_size ?? 0 }}</strong></div>
            <div class="summary-item"><span>文档数</span><strong>{{ datasetSummary.unique_doc_count ?? 0 }}</strong></div>
            <div class="summary-item"><span>有明确依据的样本</span><strong>{{ datasetSummary.grounded_sample_count ?? 0 }}</strong></div>
            <div class="summary-item"><span>平均上下文长度</span><strong>{{ datasetSummary.avg_context_length ?? 0 }}</strong></div>
          </div>
        </div>
        <div class="card compact-panel">
          <div class="panel-title">问题类型覆盖</div>
          <div v-if="taskTypeEntries.length" class="tag-list">
            <span v-for="item in taskTypeEntries" :key="item.key" class="summary-tag">{{ evaluationTaskTypeLabel(item.key) }} x {{ item.value }}</span>
          </div>
          <p v-else class="empty-text">这次还没有记录问题类型。</p>
        </div>
        <div class="card compact-panel">
          <div class="panel-title">难度分布</div>
          <div v-if="difficultyEntries.length" class="tag-list">
            <span v-for="item in difficultyEntries" :key="item.key" class="summary-tag">{{ evaluationDifficultyLabel(item.key) }} x {{ item.value }}</span>
          </div>
          <p v-else class="empty-text">这次还没有记录难度分布。</p>
        </div>
        <div class="card compact-panel">
          <div class="panel-title">是否过线</div>
          <div class="gate-status" :data-passed="state.evaluationLatest?.gate?.passed ? 'yes' : 'no'">
            {{ state.evaluationLatest?.gate?.passed ? "已通过" : "未通过" }}
          </div>
          <ul v-if="friendlyGateFailures.length" class="gate-list">
            <li v-for="failure in friendlyGateFailures" :key="failure.metric">{{ failure.message }}</li>
          </ul>
          <p v-else class="empty-text">这次没有发现明显问题。</p>
        </div>
      </div>
      <p v-else class="empty-text">还没有抽样结果。</p>

      <h2 class="sub-section-title">最近两次变化</h2>
      <div v-if="historyComparison" class="panel-grid comparison-grid">
        <div class="card compact-panel">
          <div class="panel-title">检查方式有没有变</div>
          <div class="summary-list">
            <div class="summary-item"><span>样本总量</span><strong>{{ historyComparison.current.generated_from?.sample_limit ?? "-" }} / {{ historyComparison.previous.generated_from?.sample_limit ?? "-" }}</strong></div>
            <div class="summary-item"><span>手工样本占比</span><strong>{{ formatRatio(historyComparison.current.generated_from?.manual_sample_ratio) }} / {{ formatRatio(historyComparison.previous.generated_from?.manual_sample_ratio) }}</strong></div>
            <div class="summary-item"><span>手工样本策略</span><strong>{{ historyComparison.current.generated_from?.prioritize_all_manual_samples ? "尽量全带上" : "按比例抽样" }} / {{ historyComparison.previous.generated_from?.prioritize_all_manual_samples ? "尽量全带上" : "按比例抽样" }}</strong></div>
            <div class="summary-item"><span>涉及文档数</span><strong>{{ historyComparison.current.generated_from?.document_count ?? "-" }} / {{ historyComparison.previous.generated_from?.document_count ?? "-" }}</strong></div>
          </div>
        </div>
        <div class="card compact-panel">
          <div class="panel-title">结果是变好还是变差</div>
          <div class="comparison-metric-list">
            <div v-for="metric in comparisonMetrics" :key="metric.key" class="comparison-metric-row">
              <div class="comparison-metric-main">
                <span>{{ metric.label }}</span>
                <strong>{{ metric.text }}</strong>
              </div>
              <div class="comparison-metric-badges">
                <span class="delta-badge" :data-tone="metric.tone">{{ metric.status }}</span>
                <span v-if="metric.thresholdStatus" class="delta-badge" :data-tone="metric.thresholdTone">{{ metric.thresholdStatus }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <p v-else class="empty-text">至少要有两次检查结果，才能看到变化。</p>

      <h2 class="sub-section-title">手工样本</h2>
      <div class="panel-grid summary-grid">
        <div class="card compact-panel">
          <div class="panel-title">沉淀情况</div>
          <div class="summary-list">
            <div class="summary-item"><span>手工样本总数</span><strong>{{ manualSampleTotal }}</strong></div>
            <div class="summary-item"><span>这次参与检查</span><strong>{{ manualSampleUsed }}</strong></div>
            <div class="summary-item"><span>这次没参与</span><strong>{{ unusedManualSamples.length }}</strong></div>
            <div class="summary-item"><span>最近新增</span><strong>{{ formatDate(latestManualSampleAt) }}</strong></div>
          </div>
          <p v-if="state.evaluationDatasetSamplesPath" class="panel-path">{{ state.evaluationDatasetSamplesPath }}</p>
        </div>

        <div class="card compact-panel wide-panel">
          <div class="panel-title-row">
            <div class="panel-title">样本管理</div>
            <label class="filter-toggle">
              <input v-model="showOnlyUnused" type="checkbox" />
              <span>只看这次没参与的样本</span>
            </label>
          </div>

          <section v-if="usedManualSamplesVisible.length" class="sample-group">
            <div class="sample-group-head"><h3>这次已参与</h3><span class="group-count">{{ usedManualSamples.length }}</span></div>
            <div class="manual-sample-list">
              <article v-for="item in usedManualSamplesVisible" :key="item.sample_id" class="manual-sample-card">
                <div class="manual-sample-head"><strong>{{ item.question || "未命名问题" }}</strong><span class="history-badge" data-passed="yes">已参与</span></div>
                <div class="manual-edit-grid">
                  <textarea v-model="drafts[item.sample_id].reference" class="input sample-edit-field" rows="3" placeholder="期望答案" />
                  <textarea v-model="drafts[item.sample_id].notes" class="input sample-edit-field" rows="3" placeholder="备注" />
                </div>
                <div class="manual-meta">
                  <span>来源 {{ manualSampleSourceLabel(item.source) }}</span>
                  <span>{{ evaluationTaskTypeLabel(item.task_type || "manual_debug") }}</span>
                  <span>{{ evaluationDifficultyLabel(item.difficulty || "manual") }}</span>
                  <span>{{ formatDate(item.created_at) }}</span>
                  <span v-if="item.updated_at">更新于 {{ formatDate(item.updated_at) }}</span>
                  <span v-if="item.last_used_at">最近参与 {{ formatDate(item.last_used_at) }}</span>
                </div>
                <div class="manual-actions">
                  <button class="btn btn-primary" :disabled="state.updatingSampleId === item.sample_id" @click="saveSampleEdit(item)">{{ state.updatingSampleId === item.sample_id ? "保存中..." : "保存修改" }}</button>
                  <button class="btn btn-ghost danger-btn" :disabled="state.deletingSampleId === item.sample_id" @click="removeSample(item)">{{ state.deletingSampleId === item.sample_id ? "删除中..." : "删除样本" }}</button>
                </div>
              </article>
            </div>
          </section>

          <section v-if="unusedManualSamplesVisible.length" class="sample-group">
            <div class="sample-group-head"><h3>这次未参与</h3><span class="group-count muted">{{ unusedManualSamples.length }}</span></div>
            <div class="manual-sample-list">
              <article v-for="item in unusedManualSamplesVisible" :key="item.sample_id" class="manual-sample-card">
                <div class="manual-sample-head"><strong>{{ item.question || "未命名问题" }}</strong><span class="history-badge" data-passed="no">未参与</span></div>
                <div class="manual-edit-grid">
                  <textarea v-model="drafts[item.sample_id].reference" class="input sample-edit-field" rows="3" placeholder="期望答案" />
                  <textarea v-model="drafts[item.sample_id].notes" class="input sample-edit-field" rows="3" placeholder="备注" />
                </div>
                <div class="manual-meta">
                  <span>来源 {{ manualSampleSourceLabel(item.source) }}</span>
                  <span>{{ evaluationTaskTypeLabel(item.task_type || "manual_debug") }}</span>
                  <span>{{ evaluationDifficultyLabel(item.difficulty || "manual") }}</span>
                  <span>{{ formatDate(item.created_at) }}</span>
                  <span v-if="item.updated_at">更新于 {{ formatDate(item.updated_at) }}</span>
                </div>
                <p v-if="item.last_exclusion_detail" class="sample-reason">{{ evaluationExclusionReasonLabel(item.last_exclusion_reason) }}：{{ item.last_exclusion_detail }}</p>
                <div class="manual-actions">
                  <button class="btn btn-primary" :disabled="state.updatingSampleId === item.sample_id" @click="saveSampleEdit(item)">{{ state.updatingSampleId === item.sample_id ? "保存中..." : "保存修改" }}</button>
                  <button class="btn btn-ghost danger-btn" :disabled="state.deletingSampleId === item.sample_id" @click="removeSample(item)">{{ state.deletingSampleId === item.sample_id ? "删除中..." : "删除样本" }}</button>
                </div>
              </article>
            </div>
          </section>

          <p v-if="!usedManualSamplesVisible.length && !unusedManualSamplesVisible.length" class="empty-text">当前筛选条件下没有样本。</p>
        </div>
      </div>

      <h2 class="sub-section-title">历史记录</h2>
      <div v-if="historyCards.length" class="history-list">
        <div v-for="item in historyCards" :key="item.generated_at || item.dataset_size" class="history-item">
          <div class="history-topline">
            <strong>{{ formatDate(item.generated_at) }}</strong>
            <div class="history-top-actions">
              <span class="history-badge" :data-passed="item.gate?.passed ? 'yes' : 'no'">{{ item.gate?.passed ? "通过" : "未通过" }}</span>
              <button class="btn btn-ghost btn-sm" :disabled="state.evaluating" @click="rerunHistoryConfig(item)">{{ state.evaluating ? "检查中..." : "按这次配置重跑" }}</button>
            </div>
          </div>
          <div class="history-meta">样本数 {{ item.dataset_size ?? 0 }}，回答贴合度 {{ formatMetricValue(item.metrics?.faithfulness) }}，回答相关度 {{ formatMetricValue(item.metrics?.answer_relevancy) }}</div>
          <div class="history-meta">目标样本 {{ item.generated_from?.sample_limit ?? "-" }}，手工样本 {{ item.generated_from?.manual_sample_count_used ?? item.generated_from?.manual_sample_count ?? 0 }} / {{ item.generated_from?.manual_sample_count_total ?? 0 }}</div>
          <div class="history-config-list">
            <span class="summary-tag">手工占比 {{ formatRatio(item.generated_from?.manual_sample_ratio) }}</span>
            <span class="summary-tag">{{ item.generated_from?.prioritize_all_manual_samples ? "尽量全带上" : "按比例抽样" }}</span>
            <span class="summary-tag">文档数 {{ item.generated_from?.document_count ?? "-" }}</span>
          </div>
        </div>
      </div>
      <p v-else class="empty-text">还没有历史记录。</p>

      <h2 class="sub-section-title">原始报告</h2>
      <pre v-if="state.evaluationLatest?.markdown" class="report-box">{{ state.evaluationLatest.markdown }}</pre>
      <p v-else class="empty-text">还没有可查看的报告。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue"
import StatusMessage from "@/components/common/StatusMessage.vue"
import { evaluationDifficultyLabel, evaluationExclusionReasonLabel, evaluationTaskTypeLabel, manualSampleSourceLabel } from "@/utils/adminUi"
import { useAdminEvaluation } from "./composables/useAdminEvaluation"

type GenericMap = Record<string, any>

const { state, loadEvaluation, runEvaluation, updateManualSample, deleteManualSample, downloadRuntimeMetrics, formatPercent, formatDate } = useAdminEvaluation()

const showOnlyUnused = ref(false)
const drafts = reactive<Record<string, { reference: string; notes: string }>>({})

const datasetSummary = computed(() => state.evaluationLatest?.generated_from?.dataset_summary || null)
const metricCards = computed(() => [
  { key: "faithfulness", label: "回答是否贴合资料", value: formatMetricValue(state.evaluationLatest?.metrics?.faithfulness) },
  { key: "answer_relevancy", label: "回答是否切题", value: formatMetricValue(state.evaluationLatest?.metrics?.answer_relevancy) },
  { key: "context_precision", label: "找到的资料准不准", value: formatMetricValue(state.evaluationLatest?.metrics?.context_precision) },
  { key: "context_recall", label: "该找到的资料有没有找全", value: formatMetricValue(state.evaluationLatest?.metrics?.context_recall) },
].filter((item) => item.value !== "-"))
const difficultyEntries = computed(() => Object.entries(datasetSummary.value?.difficulty_counts || {}).map(([key, value]) => ({ key, value })))
const taskTypeEntries = computed(() => Object.entries(datasetSummary.value?.task_type_counts || {}).map(([key, value]) => ({ key, value })))
const gateFailures = computed(() => state.evaluationLatest?.gate?.failures || [])
const friendlyGateFailures = computed(() => gateFailures.value.map((failure: GenericMap) => ({ metric: failure.metric, message: gateFailureMessage(failure) })))
const historyCards = computed(() => state.evaluationHistory || [])
const historyComparison = computed(() => (historyCards.value.length >= 2 ? { current: historyCards.value[0], previous: historyCards.value[1] } : null))
const manualSampleTotal = computed(() => state.evaluationLatest?.generated_from?.manual_sample_count_total ?? state.evaluationDatasetSamplesTotal ?? 0)
const manualSampleUsed = computed(() => state.evaluationLatest?.generated_from?.manual_sample_count_used ?? 0)
const latestManualSampleAt = computed(() => state.evaluationDatasetSamples[0]?.created_at || null)
const manualRatioPercent = computed({
  get: () => Math.round((Number(state.evaluationRunConfig.manualSampleRatio ?? 1) || 0) * 100),
  set: (value: number) => {
    const normalized = Math.min(Math.max(Number(value || 0), 0), 100)
    state.evaluationRunConfig.manualSampleRatio = normalized / 100
  },
})
const manualTargetCount = computed(() => Math.ceil(Math.max(Number(state.evaluationRunConfig.sampleLimit || 1), 1) * Math.min(Math.max(Number(state.evaluationRunConfig.manualSampleRatio ?? 1), 0), 1)))
const comparisonMetrics = computed(() => ["faithfulness", "answer_relevancy", "context_precision", "context_recall"].map((key) => buildMetricComparison(key)))

const usedSignatures = computed(() => {
  const used = Number(manualSampleUsed.value || 0)
  return new Set(state.evaluationDatasetSamples.slice(0, used).map((item) => `${item.question || ""}||${item.reference || item.answer || ""}`))
})
const usedManualSamples = computed(() => (state.evaluationDatasetSamples || []).filter((item) => isManualSampleUsed(item)))
const unusedManualSamples = computed(() => (state.evaluationDatasetSamples || []).filter((item) => !isManualSampleUsed(item)))
const usedManualSamplesVisible = computed(() => (showOnlyUnused.value ? [] : usedManualSamples.value))
const unusedManualSamplesVisible = computed(() => unusedManualSamples.value)

watch(
  () => state.evaluationDatasetSamples,
  (items) => {
    for (const item of items || []) {
      drafts[item.sample_id] = { reference: item.reference || item.answer || "", notes: item.metadata?.notes || "" }
    }
  },
  { immediate: true, deep: true },
)

function formatRatio(value: number | null | undefined) {
  if (value === null || value === undefined) return "-"
  return `${Math.round(Number(value) * 100)}%`
}

function formatMetricValue(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return "-"
  const numeric = Number(value)
  if (Number.isNaN(numeric)) return String(value)
  return `${(numeric * 100).toFixed(1)}%`
}

function gateFailureMessage(failure: GenericMap) {
  const names: Record<string, string> = {
    faithfulness: "回答和资料贴合度不够",
    answer_relevancy: "回答和问题的相关度不够",
    context_precision: "找到的资料不够准确",
    context_recall: "该找到的资料没有找全",
  }
  const label = names[failure.metric] || failure.metric
  return `${label}，当前 ${formatMetricValue(failure.actual)}，要求至少 ${formatMetricValue(failure.threshold)}`
}

function gateFailed(item: GenericMap | null | undefined, metric: string) {
  const failures = item?.gate?.failures || []
  return failures.some((failure: GenericMap) => failure.metric === metric)
}

function buildMetricComparison(metric: string) {
  const labels: Record<string, string> = {
    faithfulness: "回答是否贴合资料",
    answer_relevancy: "回答是否切题",
    context_precision: "资料找得准不准",
    context_recall: "资料找得全不全",
  }
  const current = Number(historyComparison.value?.current?.metrics?.[metric])
  const previous = Number(historyComparison.value?.previous?.metrics?.[metric])
  if (Number.isNaN(current) || Number.isNaN(previous)) {
    return { key: metric, label: labels[metric] || metric, text: "-", status: "暂无数据", tone: "neutral", thresholdStatus: "", thresholdTone: "neutral" }
  }
  const delta = current - previous
  const tone = delta > 0.0001 ? "up" : delta < -0.0001 ? "down" : "flat"
  const status = tone === "up" ? "比上次更好" : tone === "down" ? "比上次更差" : "和上次差不多"
  const currentFailed = gateFailed(historyComparison.value?.current, metric)
  const previousFailed = gateFailed(historyComparison.value?.previous, metric)
  let thresholdStatus = ""
  let thresholdTone = "neutral"
  if (previousFailed && !currentFailed) {
    thresholdStatus = "这次恢复达标"
    thresholdTone = "up"
  } else if (!previousFailed && currentFailed) {
    thresholdStatus = "这次跌破标准"
    thresholdTone = "down"
  } else if (currentFailed && previousFailed) {
    thresholdStatus = "连续两次没达标"
    thresholdTone = "down"
  } else {
    thresholdStatus = "连续两次都达标"
    thresholdTone = "up"
  }
  const sign = delta > 0 ? "+" : ""
  return {
    key: metric,
    label: labels[metric] || metric,
    text: `${formatMetricValue(current)} / ${formatMetricValue(previous)} (${sign}${(delta * 100).toFixed(1)}%)`,
    status,
    tone,
    thresholdStatus,
    thresholdTone,
  }
}

function isManualSampleUsed(sample: GenericMap) {
  const signature = `${sample.question || ""}||${sample.reference || sample.answer || ""}`
  return usedSignatures.value.has(signature)
}

async function saveSampleEdit(sample: GenericMap) {
  const draft = drafts[sample.sample_id]
  if (!draft) return
  await updateManualSample(sample.sample_id, { reference: draft.reference, answer: draft.reference, metadata: { ...(sample.metadata || {}), notes: draft.notes } })
  await loadEvaluation()
}

async function removeSample(sample: GenericMap) {
  await deleteManualSample(sample.sample_id)
  await loadEvaluation()
}

async function rerunHistoryConfig(item: GenericMap) {
  const generatedFrom = item?.generated_from || {}
  state.evaluationRunConfig.sampleLimit = Math.max(Number(generatedFrom.sample_limit || 100), 1)
  state.evaluationRunConfig.prioritizeAllManualSamples = Boolean(generatedFrom.prioritize_all_manual_samples)
  state.evaluationRunConfig.manualSampleRatio = Math.min(Math.max(Number(generatedFrom.manual_sample_ratio ?? 1), 0), 1)
  await runEvaluation()
}

onMounted(() => {
  loadEvaluation()
})
</script>

<style scoped>
.summary-grid,
.comparison-grid {
  align-items: stretch;
}

.compact-panel {
  padding: 16px;
}

.wide-panel {
  grid-column: span 2;
}

.run-config-panel {
  margin: 16px 0 20px;
}

.run-config-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.config-field,
.config-toggle {
  display: grid;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.config-toggle {
  align-content: end;
}

.config-toggle input,
.filter-toggle input {
  margin: 0;
}

.compact-field {
  max-width: 160px;
}

.config-hint {
  margin-top: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}

.panel-title,
.panel-title-row {
  margin-bottom: 12px;
}

.panel-title,
.panel-title-row .panel-title,
.sample-group-head h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.panel-title-row,
.sample-group-head,
.history-topline,
.history-top-actions,
.comparison-metric-main,
.comparison-metric-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.filter-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.summary-list,
.comparison-metric-list {
  display: grid;
  gap: 10px;
}

.summary-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  color: var(--text-secondary);
}

.summary-item strong,
.comparison-metric-main strong {
  color: var(--text-primary);
  text-align: right;
}

.panel-path {
  margin-top: 12px;
  color: var(--text-tertiary);
  font-size: 12px;
  word-break: break-word;
}

.tag-list,
.history-config-list,
.comparison-metric-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.summary-tag,
.group-count,
.delta-badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--bg-surface-strong);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.delta-badge[data-tone="up"] {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
}

.delta-badge[data-tone="down"] {
  background: rgba(214, 69, 65, 0.12);
  color: #d64541;
}

.delta-badge[data-tone="flat"],
.delta-badge[data-tone="neutral"] {
  background: rgba(107, 114, 128, 0.12);
  color: #4b5563;
}

.group-count.muted {
  opacity: 0.8;
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

.sample-group + .sample-group {
  margin-top: 20px;
}

.manual-sample-list,
.history-list {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}

.manual-sample-card,
.history-item {
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-surface);
}

.manual-sample-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.manual-edit-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.sample-edit-field {
  min-height: 88px;
  resize: vertical;
}

.manual-actions,
.manual-meta,
.history-meta,
.sample-reason,
.history-config-list {
  margin-top: 10px;
}

.manual-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}

.manual-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.danger-btn {
  color: #b3261e;
}

.history-meta,
.sample-reason,
.comparison-metric-main {
  color: var(--text-secondary);
  font-size: 13px;
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

@media (max-width: 900px) {
  .wide-panel {
    grid-column: span 1;
  }

  .run-config-grid,
  .manual-edit-grid {
    grid-template-columns: 1fr;
  }

  .manual-sample-head,
  .panel-title-row,
  .sample-group-head,
  .history-topline,
  .history-top-actions,
  .summary-item,
  .comparison-metric-main,
  .comparison-metric-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .summary-item strong,
  .comparison-metric-main strong {
    text-align: left;
  }
}
</style>

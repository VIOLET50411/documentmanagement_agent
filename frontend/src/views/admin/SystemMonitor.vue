<template>
  <div class="tab-content animate-fade-in">
    <div class="stats-grid pipeline-grid">
      <div v-for="item in backendCards" :key="item.label" class="stat-card card compact">
        <span class="stat-value small">{{ item.value }}</span>
        <span class="stat-label">{{ item.label }}</span>
      </div>
    </div>

    <StatusMessage
      v-if="state.error"
      tone="error"
      title="系统状态暂时不可用"
      :message="state.error"
      dismissible
      action-label="重新加载"
      @dismiss="state.error = ''"
      @action="reloadMonitor"
    />

    <div class="card section-card">
      <div class="section-header">
        <h2>公开语料导出</h2>
        <div class="action-group">
          <button class="refresh-btn" @click="exportPublicCorpusAsync" :disabled="state.exportingPublicCorpus">
            {{ state.exportingPublicCorpus ? "导出中..." : "开始导出" }}
          </button>
        </div>
      </div>
      <div class="filters-grid public-corpus-grid">
        <input v-model="state.publicCorpusForm.dataset_name" class="input" type="text" placeholder="数据集名称" />
        <input v-model="state.publicCorpusForm.tenant_id" class="input" type="text" placeholder="租户 ID" />
        <input v-model.number="state.publicCorpusForm.train_ratio" class="input" type="number" min="0.5" max="0.98" step="0.01" />
      </div>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact"><span class="stat-value small">{{ state.publicCorpusLatest?.record_count ?? 0 }}</span><span class="stat-label">原始记录数</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.publicCorpusLatest?.chunk_count ?? 0 }}</span><span class="stat-label">切分后片段数</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.publicCorpusLatest?.training_readiness?.train_records ?? 0 }}</span><span class="stat-label">训练样本数</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.publicCorpusLatest?.training_readiness?.ready_for_sft ? "可以训练" : "暂不可训练" }}</span><span class="stat-label">训练准备情况</span></div>
      </div>
      <ul v-if="state.publicCorpusLatest?.exists" class="list">
        <li class="list-item stacked">
          <span class="list-title">最近一次导出</span>
          <span class="list-meta">数据集：{{ state.publicCorpusLatest?.dataset_name || state.publicCorpusForm.dataset_name }}</span>
          <span class="list-meta">导出目录：{{ state.publicCorpusLatest?.export_dir || "-" }}</span>
          <span class="list-meta">Manifest：{{ state.publicCorpusLatest?.manifest_path || "-" }}</span>
          <span class="list-meta">生成时间：{{ formatDate(state.publicCorpusLatest?.generated_at) }}</span>
          <span class="list-meta">任务 ID：{{ state.publicCorpusTaskId || "-" }}</span>
        </li>
      </ul>
      <EmptyState v-else title="当前还没有公开语料导出结果。" />
    </div>

    <div class="card section-card">
      <h2>平台准备情况</h2>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact"><span class="stat-value small">{{ state.readiness?.score ?? "-" }}</span><span class="stat-label">总体评分</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.readiness?.ready ? "已就绪" : "未就绪" }}</span><span class="stat-label">当前状态</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.readiness?.blockers?.length ?? 0 }}</span><span class="stat-label">阻塞项</span></div>
      </div>
      <ul v-if="state.readiness?.blockers?.length" class="list">
        <li v-for="item in state.readiness.blockers" :key="item.id" class="list-item">
          <span class="list-title">{{ blockerLabel(item.id) }}</span>
          <span class="list-meta">{{ item.message }}</span>
        </li>
      </ul>
      <EmptyState v-else title="当前没有阻塞项，平台可以正常工作。" />
    </div>

    <div class="card section-card">
      <div class="section-header">
        <h2>检索健康度</h2>
        <div class="action-group">
          <button v-if="!state.retrievalIntegrity?.healthy && state.retrievalIntegrity" class="btn btn-secondary btn-sm" @click="jumpToInspect">去运行排查看看</button>
        </div>
      </div>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact"><span class="stat-value small">{{ state.retrievalIntegrity?.score ?? "-" }}</span><span class="stat-label">健康评分</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.retrievalIntegrity?.healthy ? "正常" : "有风险" }}</span><span class="stat-label">当前状态</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ state.retrievalIntegrity?.stats?.sample_size ?? 0 }}</span><span class="stat-label">抽查样本数</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ formatPercent(state.retrievalIntegrity?.stats?.milvus_sample_recall) }}</span><span class="stat-label">向量召回率</span></div>
      </div>
      <ul v-if="state.retrievalIntegrity?.blockers?.length" class="list">
        <li v-for="item in state.retrievalIntegrity.blockers" :key="item.id" class="list-item">
          <span class="list-title">{{ blockerLabel(item.id) }}</span>
          <span class="list-meta">{{ item.message }}</span>
        </li>
      </ul>
      <EmptyState v-else title="检索健康度检查已通过。" />
    </div>

    <div class="card section-card">
      <h2>检索后端表现</h2>
      <table v-if="retrievalMetricsRows.length" class="data-table">
        <thead>
          <tr>
            <th>后端</th>
            <th>请求数</th>
            <th>成功率</th>
            <th>错误率</th>
            <th>超时率</th>
            <th>P95 延迟(ms)</th>
            <th>最近错误</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in retrievalMetricsRows" :key="row.backend">
            <td>{{ backendNameLabel(row.backend) }}</td>
            <td>{{ row.requests }}</td>
            <td>{{ formatPercent(row.success_rate) }}</td>
            <td>{{ formatPercent(row.error_rate) }}</td>
            <td>{{ formatPercent(row.timeout_rate) }}</td>
            <td>{{ row.latency_p95_ms ?? "-" }}</td>
            <td>{{ backendErrorLabel(row.last_error) }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前还没有检索后端统计。" />
    </div>

    <div class="card section-card">
      <h2>慢请求摘要</h2>
      <table v-if="state.requestMetrics.length" class="data-table">
        <thead>
          <tr>
            <th>方法</th>
            <th>路径</th>
            <th>请求数</th>
            <th>平均耗时(ms)</th>
            <th>最大耗时(ms)</th>
            <th>慢请求次数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in state.requestMetrics" :key="`${row.method}-${row.path}`">
            <td>{{ row.method }}</td>
            <td>{{ requestPathLabel(row.path) }}</td>
            <td>{{ row.count }}</td>
            <td>{{ row.avg_ms }}</td>
            <td>{{ row.max_ms }}</td>
            <td>{{ row.slow_count }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前还没有请求摘要。" />
    </div>

    <div class="card section-card">
      <h2>前端最近请求</h2>
      <table v-if="state.frontendHttpTraces.length" class="data-table">
        <thead>
          <tr>
            <th>开始时间</th>
            <th>方法</th>
            <th>路径</th>
            <th>状态</th>
            <th>浏览器耗时(ms)</th>
            <th>服务端耗时</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in state.frontendHttpTraces" :key="`${row.startedAt}-${row.url}-${index}`">
            <td>{{ formatDate(row.startedAt) }}</td>
            <td>{{ row.method }}</td>
            <td>{{ requestPathLabel(row.url) }}</td>
            <td>{{ frontendTraceStatusLabel(row.status) }}</td>
            <td>{{ row.durationMs }}</td>
            <td>{{ row.responseTimeHeader || row.serverTiming || "-" }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前还没有前端请求记录。" />
    </div>

    <div class="card section-card">
      <div class="section-header">
        <h2>恢复点汇总</h2>
      </div>
      <table v-if="runtimeStore.checkpointSummary.length" class="data-table">
        <thead>
          <tr>
            <th>会话</th>
            <th>停在步骤</th>
            <th>轮次</th>
            <th>恢复点数量</th>
            <th>能否继续</th>
            <th>系统理解</th>
            <th>检索用语</th>
            <th>最近时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in runtimeStore.checkpointSummary" :key="row.session_id">
            <td>{{ row.session_id }}</td>
            <td>{{ checkpointNodeLabel(row.latest_node_name) }}</td>
            <td>{{ row.latest_iteration }}</td>
            <td>{{ row.checkpoint_count }}</td>
            <td>{{ row.resumable ? "可以继续" : "暂不可继续" }}</td>
            <td>{{ row.intent || "-" }}</td>
            <td>{{ row.rewritten_query || "-" }}</td>
            <td>{{ formatDate(row.latest_at) }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前还没有恢复点汇总。" />
    </div>

    <div class="card section-card">
      <h2>工具判断统计（近 {{ runtimeStore.toolDecisionSummary?.window_hours ?? 24 }} 小时）</h2>
      <div class="filters-grid">
        <select v-model="runtimeStore.toolFilters.decision" class="input">
          <option value="">全部判断结果</option>
          <option value="allow">直接放行</option>
          <option value="ask">需要确认</option>
          <option value="deny">直接拦截</option>
        </select>
        <select v-model="runtimeStore.toolFilters.source" class="input">
          <option value="">全部来源</option>
          <option value="rbac">权限规则</option>
          <option value="security_audit">安全审计</option>
          <option value="tool_spec">工具说明</option>
          <option value="registry">工具目录</option>
        </select>
        <input v-model="runtimeStore.toolFilters.tool_name" class="input" type="text" placeholder="按工具名称筛选" />
      </div>
      <div class="action-group">
        <button class="btn btn-ghost" @click="downloadRuntimeToolSummary">导出当前统计（JSON）</button>
      </div>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.total ?? 0 }}</span><span class="stat-label">总判断数</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.allow ?? 0 }}</span><span class="stat-label">直接放行</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.ask ?? 0 }}</span><span class="stat-label">需要确认</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.deny ?? 0 }}</span><span class="stat-label">直接拦截</span></div>
      </div>
      <table v-if="runtimeStore.toolMatrixRows.length" class="data-table">
        <thead>
          <tr>
            <th>工具</th>
            <th>直接放行</th>
            <th>需要确认</th>
            <th>直接拦截</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in runtimeStore.toolMatrixRows" :key="row.tool_name">
            <td>{{ row.tool_name }}</td>
            <td>{{ row.allow || 0 }}</td>
            <td>{{ row.ask || 0 }}</td>
            <td>{{ row.deny || 0 }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前还没有工具判断统计。" />

      <h2 class="sub-section-title">按原因汇总</h2>
      <table v-if="runtimeStore.reasonMatrixRows.length" class="data-table">
        <thead>
          <tr>
            <th>原因</th>
            <th>直接放行</th>
            <th>需要确认</th>
            <th>直接拦截</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in runtimeStore.reasonMatrixRows" :key="row.reason">
            <td>{{ toolDecisionReasonLabel(row.reason) }}</td>
            <td>{{ row.allow || 0 }}</td>
            <td>{{ row.ask || 0 }}</td>
            <td>{{ row.deny || 0 }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前还没有按原因汇总的数据。" />

      <h2 class="sub-section-title">按小时变化</h2>
      <table v-if="runtimeStore.trendRows.length" class="data-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>直接放行</th>
            <th>需要确认</th>
            <th>直接拦截</th>
            <th>未识别</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in runtimeStore.trendRows" :key="row.hour">
            <td>{{ formatDate(row.hour) }}</td>
            <td>{{ row.allow || 0 }}</td>
            <td>{{ row.ask || 0 }}</td>
            <td>{{ row.deny || 0 }}</td>
            <td>{{ row.unknown || 0 }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前还没有小时级趋势数据。" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue"
import { useRouter } from "vue-router"
import EmptyState from "@/components/common/EmptyState.vue"
import StatusMessage from "@/components/common/StatusMessage.vue"
import { useRuntimeStore } from "@/stores/runtime"
import { blockerLabel, checkpointNodeLabel, toolDecisionReasonLabel } from "@/utils/adminUi"
import { useAdminBackends } from "./composables/useAdminBackends"

const router = useRouter()
const runtimeStore = useRuntimeStore()
const {
  state,
  backendCards,
  retrievalMetricsRows,
  loadBackends,
  loadRetrievalIntegrity,
  loadPublicCorpusLatest,
  exportPublicCorpusAsync,
  downloadRuntimeToolSummary,
  formatDate,
  formatPercent,
  backendNameLabel,
  requestPathLabel,
  frontendTraceStatusLabel,
} = useAdminBackends()

let timer: number
let stopToolFilterWatch: (() => void) | null = null
let visibilityHandler: (() => void) | null = null

function jumpToInspect() {
  router.push({ query: { tab: "inspect" } })
}

function reloadMonitor() {
  loadBackends()
  void loadRetrievalIntegrity()
  void loadPublicCorpusLatest()
  runtimeStore.loadToolDecisionSummary()
  runtimeStore.loadCheckpointSummary()
}

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
    loadBackends()
    runtimeStore.loadToolDecisionSummary()
    runtimeStore.loadCheckpointSummary()
  }, 30000)
}

onMounted(async () => {
  reloadMonitor()

  if (!runtimeStore.toolDecisionSummary) {
    await runtimeStore.loadToolDecisionSummary()
  }
  if (!runtimeStore.checkpointSummary.length) {
    await runtimeStore.loadCheckpointSummary()
  }

  stopToolFilterWatch = watch(
    () => ({ ...runtimeStore.toolFilters }),
    () => {
      runtimeStore.loadToolDecisionSummary()
    },
    { deep: true },
  )

  startPolling()
  visibilityHandler = () => {
    if (document.visibilityState === "visible") {
      reloadMonitor()
      startPolling()
      return
    }
    stopPolling()
  }
  document.addEventListener("visibilitychange", visibilityHandler)
})

onUnmounted(() => {
  stopPolling()
  if (stopToolFilterWatch) stopToolFilterWatch()
  if (visibilityHandler) {
    document.removeEventListener("visibilitychange", visibilityHandler)
  }
})

function backendErrorLabel(value?: string | null) {
  if (!value) return "当前没有错误"
  const normalized = value.toLowerCase()
  if (/timeout|timed out/.test(normalized)) return "最近一次请求超时。"
  if (/permission|forbidden|denied/.test(normalized)) return "最近一次请求被拒绝。"
  if (/network|connect|connection|unreachable/.test(normalized)) return "最近一次请求无法连通后端。"
  return value
}
</script>

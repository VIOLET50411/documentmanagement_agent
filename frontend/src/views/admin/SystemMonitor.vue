<template>
  <div class="tab-content animate-fade-in">
    <div class="stats-grid pipeline-grid">
      <div v-for="item in backendCards" :key="item.label" class="stat-card card compact">
        <span class="stat-value small">{{ item.value }}</span>
        <span class="stat-label">{{ item.label }}</span>
      </div>
    </div>

    <div class="card section-card">
      <div class="section-header">
        <h2>公开语料冷启动导出</h2>
        <div class="action-group">
          <button class="refresh-btn" @click="loadPublicCorpusLatest" :disabled="dashboard.loadingPublicCorpusLatest">
            {{ dashboard.loadingPublicCorpusLatest ? "加载中..." : "刷新摘要" }}
          </button>
          <button class="refresh-btn" @click="exportPublicCorpusAsync" :disabled="dashboard.exportingPublicCorpus">
            {{ dashboard.exportingPublicCorpus ? "导出中..." : "启动异步导出" }}
          </button>
        </div>
      </div>
      <div class="filters-grid public-corpus-grid">
        <input v-model="dashboard.publicCorpusForm.dataset_name" class="input" type="text" placeholder="数据集名称" />
        <input v-model="dashboard.publicCorpusForm.tenant_id" class="input" type="text" placeholder="租户 ID" />
        <input v-model.number="dashboard.publicCorpusForm.train_ratio" class="input" type="number" min="0.5" max="0.98" step="0.01" />
      </div>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.publicCorpusLatest?.record_count ?? 0 }}</span>
          <span class="stat-label">原始记录数</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.publicCorpusLatest?.chunk_count ?? 0 }}</span>
          <span class="stat-label">切块数</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.publicCorpusLatest?.training_readiness?.train_records ?? 0 }}</span>
          <span class="stat-label">训练集样本</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.publicCorpusLatest?.training_readiness?.ready_for_sft ? "READY" : "NOT READY" }}</span>
          <span class="stat-label">SFT 就绪</span>
        </div>
      </div>
      <ul v-if="dashboard.publicCorpusLatest?.exists" class="list">
        <li class="list-item stacked">
          <span class="list-title">最近导出</span>
          <span class="list-meta">数据集：{{ dashboard.publicCorpusLatest?.dataset_name || dashboard.publicCorpusForm.dataset_name }}</span>
          <span class="list-meta">导出目录：{{ dashboard.publicCorpusLatest?.export_dir || "-" }}</span>
          <span class="list-meta">Manifest：{{ dashboard.publicCorpusLatest?.manifest_path || "-" }}</span>
          <span class="list-meta">生成时间：{{ formatDate(dashboard.publicCorpusLatest?.generated_at) }}</span>
          <span class="list-meta">任务 ID：{{ dashboard.publicCorpusTaskId || "-" }}</span>
        </li>
      </ul>
      <p v-else class="empty-text">暂无公开语料导出结果。</p>
    </div>

    <div class="card section-card">
      <h2>平台就绪度</h2>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.readiness?.score ?? "-" }}</span>
          <span class="stat-label">Readiness Score</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.readiness?.ready ? "READY" : "NOT READY" }}</span>
          <span class="stat-label">总体状态</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.readiness?.blockers?.length ?? 0 }}</span>
          <span class="stat-label">阻塞项</span>
        </div>
      </div>
      <ul v-if="dashboard.readiness?.blockers?.length" class="list">
        <li v-for="item in dashboard.readiness.blockers" :key="item.id" class="list-item">
          <span class="list-title">{{ item.id }}</span>
          <span class="list-meta">{{ item.message }}</span>
        </li>
      </ul>
      <p v-else class="empty-text">当前没有阻塞项。</p>
    </div>

    <div class="card section-card">
      <h2>检索一致性健康度</h2>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.retrievalIntegrity?.score ?? "-" }}</span>
          <span class="stat-label">Integrity Score</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.retrievalIntegrity?.healthy ? "HEALTHY" : "DEGRADED" }}</span>
          <span class="stat-label">总体状态</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ dashboard.retrievalIntegrity?.stats?.sample_size ?? 0 }}</span>
          <span class="stat-label">抽样回查数</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ formatPercent(dashboard.retrievalIntegrity?.stats?.milvus_sample_recall) }}</span>
          <span class="stat-label">Milvus 召回率</span>
        </div>
      </div>
      <ul v-if="dashboard.retrievalIntegrity?.blockers?.length" class="list">
        <li v-for="item in dashboard.retrievalIntegrity.blockers" :key="item.id" class="list-item">
          <span class="list-title">{{ item.id }}</span>
          <span class="list-meta">{{ item.message }}</span>
        </li>
      </ul>
      <p v-else class="empty-text">检索一致性检查通过。</p>
    </div>

    <div class="card section-card">
      <h2>检索后端可观测指标</h2>
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
            <td>{{ row.backend }}</td>
            <td>{{ row.requests }}</td>
            <td>{{ formatPercent(row.success_rate) }}</td>
            <td>{{ formatPercent(row.error_rate) }}</td>
            <td>{{ formatPercent(row.timeout_rate) }}</td>
            <td>{{ row.latency_p95_ms ?? "-" }}</td>
            <td>{{ row.last_error || "-" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无检索后端指标。</p>
    </div>

    <div class="card section-card">
      <div class="section-header">
        <h2>Runtime 检查点恢复摘要</h2>
        <button class="refresh-btn" @click="runtimeStore.loadCheckpointSummary()" :disabled="runtimeStore.loadingCheckpointSummary">
          {{ runtimeStore.loadingCheckpointSummary ? "加载中..." : "刷新检查点" }}
        </button>
      </div>
      <table v-if="runtimeStore.checkpointSummary.length" class="data-table">
        <thead>
          <tr>
            <th>会话</th>
            <th>最新节点</th>
            <th>迭代</th>
            <th>检查点数</th>
            <th>可恢复</th>
            <th>意图</th>
            <th>改写查询</th>
            <th>最近时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in runtimeStore.checkpointSummary" :key="row.session_id">
            <td>{{ row.session_id }}</td>
            <td>{{ row.latest_node_name }}</td>
            <td>{{ row.latest_iteration }}</td>
            <td>{{ row.checkpoint_count }}</td>
            <td>{{ row.resumable ? "是" : "否" }}</td>
            <td>{{ row.intent || "-" }}</td>
            <td>{{ row.rewritten_query || "-" }}</td>
            <td>{{ formatDate(row.latest_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无运行时检查点摘要。</p>
    </div>

    <div class="card section-card">
      <h2>Runtime 工具治理统计（近 {{ runtimeStore.toolDecisionSummary?.window_hours ?? 24 }} 小时）</h2>
      <div class="filters-grid">
        <select v-model="runtimeStore.toolFilters.decision" class="input">
          <option value="">全部决策</option>
          <option value="allow">allow</option>
          <option value="ask">ask</option>
          <option value="deny">deny</option>
        </select>
        <select v-model="runtimeStore.toolFilters.source" class="input">
          <option value="">全部来源</option>
          <option value="rbac">rbac</option>
          <option value="security_audit">security_audit</option>
          <option value="tool_spec">tool_spec</option>
          <option value="registry">registry</option>
        </select>
        <input v-model="runtimeStore.toolFilters.tool_name" class="input" type="text" placeholder="按工具名筛选（模糊）" />
        <button class="refresh-btn" @click="runtimeStore.loadToolDecisionSummary()" :disabled="runtimeStore.loadingToolSummary">
          {{ runtimeStore.loadingToolSummary ? "加载中..." : "应用筛选" }}
        </button>
      </div>
      <div class="action-group">
        <button class="btn btn-ghost" @click="downloadRuntimeToolSummary">导出当前统计（JSON）</button>
      </div>
      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact">
          <span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.total ?? 0 }}</span>
          <span class="stat-label">总决策数</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.allow ?? 0 }}</span>
          <span class="stat-label">allow</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.ask ?? 0 }}</span>
          <span class="stat-label">ask</span>
        </div>
        <div class="stat-card card compact">
          <span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.deny ?? 0 }}</span>
          <span class="stat-label">deny</span>
        </div>
      </div>
      <table v-if="runtimeStore.toolMatrixRows.length" class="data-table">
        <thead><tr><th>工具</th><th>allow</th><th>ask</th><th>deny</th></tr></thead>
        <tbody>
          <tr v-for="row in runtimeStore.toolMatrixRows" :key="row.tool_name">
            <td>{{ row.tool_name }}</td>
            <td>{{ row.allow || 0 }}</td>
            <td>{{ row.ask || 0 }}</td>
            <td>{{ row.deny || 0 }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无工具决策聚合数据。</p>

      <h2 class="sub-section-title">按原因聚合</h2>
      <table v-if="runtimeStore.reasonMatrixRows.length" class="data-table">
        <thead><tr><th>原因</th><th>allow</th><th>ask</th><th>deny</th></tr></thead>
        <tbody>
          <tr v-for="row in runtimeStore.reasonMatrixRows" :key="row.reason">
            <td>{{ row.reason }}</td>
            <td>{{ row.allow || 0 }}</td>
            <td>{{ row.ask || 0 }}</td>
            <td>{{ row.deny || 0 }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无按原因聚合数据。</p>

      <h2 class="sub-section-title">小时趋势</h2>
      <table v-if="runtimeStore.trendRows.length" class="data-table">
        <thead><tr><th>小时</th><th>allow</th><th>ask</th><th>deny</th><th>unknown</th></tr></thead>
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
      <p v-else class="empty-text">暂无趋势数据。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue"
import { useRuntimeStore } from "@/stores/runtime"

const runtimeStore = useRuntimeStore()

defineProps<{
  dashboard: Record<string, any>
  backendCards: Array<{ label: string; value: string | number }>
  retrievalMetricsRows: Array<Record<string, any>>
  formatDate: (value?: string | null) => string
  formatPercent: (value?: number | null) => string
  loadPublicCorpusLatest: () => Promise<void>
  exportPublicCorpusAsync: () => Promise<void>
  downloadRuntimeToolSummary: () => void
}>()

onMounted(async () => {
  if (!runtimeStore.toolDecisionSummary) {
    await runtimeStore.loadToolDecisionSummary()
  }
  if (!runtimeStore.checkpointSummary.length) {
    await runtimeStore.loadCheckpointSummary()
  }
})
</script>

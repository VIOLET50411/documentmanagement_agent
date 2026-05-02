<template>
  <div class="tasks-page">
    <header class="tasks-hero">
      <div>
        <p class="tasks-kicker">任务中心</p>
        <h2>统一查看运行、入库、训练与恢复任务</h2>
        <p class="tasks-copy">把原本散在管理页和对话页的运行态汇总到一处，便于排查链路阻塞、失败类型和恢复点。</p>
      </div>
      <button class="btn btn-primary" :disabled="tasksStore.loading" @click="tasksStore.loadDashboard()">
        {{ tasksStore.loading ? "刷新中…" : "刷新任务中心" }}
      </button>
    </header>

    <p v-if="tasksStore.error" class="error-banner">{{ tasksStore.error }}</p>

    <section class="summary-grid">
      <article class="summary-card card-shell">
        <span>运行任务</span>
        <strong>{{ tasksStore.runtimeTasks.length }}</strong>
        <small>最近保留的 Runtime 标准任务</small>
      </article>
      <article class="summary-card card-shell">
        <span>入库任务</span>
        <strong>{{ activePipelineJobs.length }}</strong>
        <small>排队、处理中或失败待重试的文档任务</small>
      </article>
      <article class="summary-card card-shell">
        <span>训练任务</span>
        <strong>{{ tasksStore.trainingJobs.length }}</strong>
        <small>公开语料、企业语料和模型训练作业</small>
      </article>
      <article class="summary-card card-shell">
        <span>可恢复会话</span>
        <strong>{{ resumableCheckpointCount }}</strong>
        <small>具备检查点恢复条件的运行会话</small>
      </article>
    </section>

    <section class="metric-grid">
      <article class="metric-card card-shell">
        <span>TTFT P95</span>
        <strong>{{ tasksStore.runtimeMetrics?.summary?.ttft_ms_p95 ?? "-" }} ms</strong>
      </article>
      <article class="metric-card card-shell">
        <span>完成耗时 P95</span>
        <strong>{{ tasksStore.runtimeMetrics?.summary?.completion_ms_p95 ?? "-" }} ms</strong>
      </article>
      <article class="metric-card card-shell">
        <span>回退率</span>
        <strong>{{ percent(tasksStore.runtimeMetrics?.summary?.fallback_rate) }}</strong>
      </article>
      <article class="metric-card card-shell">
        <span>工具拒绝率</span>
        <strong>{{ percent(tasksStore.runtimeMetrics?.summary?.deny_rate) }}</strong>
      </article>
      <article class="metric-card card-shell">
        <span>平均工具调用</span>
        <strong>{{ tasksStore.runtimeMetrics?.summary?.avg_tool_calls ?? "-" }}</strong>
      </article>
      <article class="metric-card card-shell">
        <span>SSE 断连</span>
        <strong>{{ tasksStore.runtimeMetrics?.summary?.sse_disconnects ?? 0 }}</strong>
      </article>
    </section>

    <div class="tasks-layout">
      <section class="panel card-shell">
        <div class="panel-head">
          <div>
            <h3>Runtime 任务</h3>
            <p>统一状态机 `pending -> running -> completed|failed|killed`。</p>
          </div>
        </div>
        <div class="task-list">
          <article v-for="item in tasksStore.runtimeTasks" :key="item.task_id" class="task-row">
            <div class="task-main">
              <div class="task-line">
                <strong>{{ item.description || item.type || "运行任务" }}</strong>
                <span class="status-pill" :data-status="item.status">{{ statusLabel(item.status) }}</span>
              </div>
              <div class="task-meta">
                <span>类型：{{ item.type || "-" }}</span>
                <span>Trace：{{ item.trace_id || "-" }}</span>
                <span>重试：{{ item.retries ?? 0 }}</span>
              </div>
            </div>
            <div class="task-side">
              <span>{{ formatTime(item.updated_at || item.end_time || item.start_time) }}</span>
              <small>{{ item.stage || "standard" }}</small>
            </div>
          </article>
          <p v-if="tasksStore.runtimeTasks.length === 0" class="empty-text">最近没有 Runtime 任务。</p>
        </div>
      </section>

      <section class="panel card-shell">
        <div class="panel-head">
          <div>
            <h3>文档入库任务</h3>
            <p>聚合上传、解析、分块、索引等文档处理阶段。</p>
          </div>
        </div>
        <div class="task-list">
          <article v-for="item in activePipelineJobs" :key="item.doc_id" class="task-row">
            <div class="task-main">
              <div class="task-line">
                <strong>{{ item.title || item.doc_id }}</strong>
                <span class="status-pill" :data-status="item.status">{{ pipelineStatusLabel(item.status) }}</span>
              </div>
              <div class="task-meta">
                <span>进度：{{ item.percentage ?? 0 }}%</span>
                <span>尝试次数：{{ item.attempt ?? 0 }}</span>
                <span v-if="item.detail">{{ item.detail }}</span>
              </div>
              <p v-if="item.error_message" class="task-error">{{ item.error_message }}</p>
            </div>
            <div class="task-side">
              <span>{{ formatTime(item.updated_at) }}</span>
              <small>{{ item.task_id || "未绑定任务 ID" }}</small>
            </div>
          </article>
          <p v-if="activePipelineJobs.length === 0" class="empty-text">当前没有活动中的文档处理任务。</p>
        </div>
      </section>
    </div>

    <div class="tasks-layout">
      <section class="panel card-shell">
        <div class="panel-head">
          <div>
            <h3>训练任务</h3>
            <p>查看数据导出、LoRA/SFT、产物注册和激活前状态。</p>
          </div>
          <span class="panel-note">
            活跃模型：{{ tasksStore.trainingSummary?.active_model?.model_name || "未激活" }}
          </span>
        </div>
        <div class="task-list">
          <article v-for="item in tasksStore.trainingJobs" :key="item.id" class="task-row">
            <div class="task-main">
              <div class="task-line">
                <strong>{{ item.target_model_name || item.dataset_name || item.id }}</strong>
                <span class="status-pill" :data-status="item.status">{{ statusLabel(item.status) }}</span>
              </div>
              <div class="task-meta">
                <span>阶段：{{ item.stage || "-" }}</span>
                <span>Provider：{{ item.provider || "-" }}</span>
                <span>样本：{{ item.train_records ?? 0 }}/{{ item.val_records ?? 0 }}</span>
              </div>
              <p v-if="item.error_message" class="task-error">{{ item.error_message }}</p>
            </div>
            <div class="task-side">
              <span>{{ formatTime(item.updated_at || item.created_at) }}</span>
              <small>{{ item.runtime_task_id || "无 runtime 任务" }}</small>
            </div>
          </article>
          <p v-if="tasksStore.trainingJobs.length === 0" class="empty-text">当前没有训练任务记录。</p>
        </div>
      </section>

      <section class="panel card-shell">
        <div class="panel-head">
          <div>
            <h3>检查点恢复摘要</h3>
            <p>用于恢复多轮会话和中断前的运行节点。</p>
          </div>
        </div>
        <div class="checkpoint-list">
          <article v-for="item in tasksStore.checkpointSummary" :key="item.session_id" class="checkpoint-row">
            <div>
              <strong>{{ item.session_id }}</strong>
              <p>{{ item.latest_node_name }} · 迭代 {{ item.latest_iteration }}</p>
            </div>
            <div class="checkpoint-side">
              <span class="status-pill" :data-status="item.resumable ? 'completed' : 'failed'">
                {{ item.resumable ? "可恢复" : "待补齐" }}
              </span>
              <small>{{ formatTime(item.latest_at) }}</small>
            </div>
          </article>
          <p v-if="tasksStore.checkpointSummary.length === 0" class="empty-text">暂无运行时检查点摘要。</p>
        </div>
      </section>
    </div>

    <section class="panel card-shell">
      <div class="panel-head">
        <div>
          <h3>运行轨迹回放</h3>
          <p>按 `trace_id` 回放一次请求的阶段流，定位降级、工具拒绝和最终失败点。</p>
        </div>
      </div>

      <div class="trace-toolbar">
        <input
          v-model="traceId"
          class="input trace-input"
          type="text"
          placeholder="输入 trace_id，例如 runtime-xxx / UUID"
        />
        <button class="btn btn-primary" :disabled="replayingTrace || !traceId.trim()" @click="loadTraceReplay">
          {{ replayingTrace ? "回放中…" : "回放轨迹" }}
        </button>
      </div>

      <p v-if="traceError" class="task-error">{{ traceError }}</p>

      <div v-if="traceEvents.length" class="trace-list">
        <article v-for="(event, index) in traceEvents" :key="`${event.event_id || event.sequence_num || index}`" class="trace-row">
          <div class="trace-seq">{{ event.sequence_num ?? index + 1 }}</div>
          <div class="trace-main">
            <div class="task-line">
              <strong>{{ traceStatusLabel(event.status || event.type) }}</strong>
              <span class="status-pill" :data-status="event.status || event.type">{{ event.source || "runtime" }}</span>
            </div>
            <div class="task-meta">
              <span>Trace：{{ event.trace_id || traceId }}</span>
              <span v-if="event.event_id">Event：{{ event.event_id }}</span>
              <span v-if="event.fallback_reason">回退：{{ event.fallback_reason }}</span>
            </div>
            <p class="trace-message">{{ event.message || event.msg || event.answer || event.content || "无附加内容" }}</p>
          </div>
          <div class="task-side">
            <span>{{ formatTime(event.timestamp || event.created_at) }}</span>
            <small>{{ event.degraded ? "已降级" : "正常" }}</small>
          </div>
        </article>
      </div>
      <p v-else class="empty-text">输入 `trace_id` 后可查看一次完整运行轨迹。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { adminApi } from "@/api/admin"
import { useTasksStore } from "@/stores/tasks"

const tasksStore = useTasksStore()
const traceId = ref("")
const traceEvents = ref<Record<string, any>[]>([])
const replayingTrace = ref(false)
const traceError = ref("")

const activePipelineJobs = computed(() =>
  tasksStore.pipelineJobs.filter((item) =>
    ["queued", "parsing", "chunking", "indexing", "retrying", "failed", "partial_failed"].includes(item.status)
  )
)

const resumableCheckpointCount = computed(
  () => tasksStore.checkpointSummary.filter((item) => Boolean(item.resumable)).length
)

onMounted(() => {
  if (!tasksStore.updatedAt) {
    tasksStore.loadDashboard()
    return
  }
  tasksStore.loadDashboard()
})

async function loadTraceReplay() {
  replayingTrace.value = true
  traceError.value = ""
  traceEvents.value = []
  try {
    const response = await adminApi.replayRuntimeTrace(traceId.value.trim())
    traceEvents.value = response.events || []
    if (!traceEvents.value.length) {
      traceError.value = "没有找到这条运行轨迹，或该轨迹不属于当前租户。"
    }
  } catch (caught: any) {
    traceError.value = caught?.response?.data?.detail || "运行轨迹回放失败。"
  } finally {
    replayingTrace.value = false
  }
}

function percent(value: number | null | undefined) {
  if (value === null || value === undefined) return "-"
  return `${(Number(value) * 100).toFixed(1)}%`
}

function formatTime(value: string | null | undefined) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function statusLabel(status: string | null | undefined) {
  const map: Record<string, string> = {
    pending: "待执行",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    killed: "已终止",
  }
  return map[status || ""] || (status || "未知")
}

function pipelineStatusLabel(status: string | null | undefined) {
  const map: Record<string, string> = {
    queued: "排队中",
    parsing: "解析中",
    chunking: "切块中",
    indexing: "索引中",
    retrying: "重试中",
    failed: "失败",
    partial_failed: "部分失败",
    ready: "已完成",
  }
  return map[status || ""] || (status || "未知")
}

function traceStatusLabel(status: string | null | undefined) {
  const map: Record<string, string> = {
    thinking: "问题理解",
    searching: "知识检索",
    reading: "证据读取",
    tool_call: "工具调用",
    streaming: "回答生成",
    done: "完成",
    error: "失败",
  }
  return map[status || ""] || (status || "运行事件")
}
</script>

<style scoped>
.tasks-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.card-shell {
  border: 1px solid var(--border-color);
  border-radius: 28px;
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.tasks-hero,
.panel-head,
.task-line,
.task-meta,
.task-side,
.checkpoint-row,
.checkpoint-side {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tasks-hero,
.panel-head,
.checkpoint-row {
  justify-content: space-between;
}

.tasks-kicker {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.tasks-hero h2 {
  margin-top: 8px;
  font-size: clamp(1.7rem, 1vw + 1.4rem, 2.35rem);
  line-height: 1.1;
  font-family: "Manrope", "PingFang SC", "Microsoft YaHei UI", sans-serif;
}

.tasks-copy {
  margin-top: 10px;
  max-width: 760px;
  color: var(--text-secondary);
}

.error-banner {
  padding: 14px 18px;
  border-radius: 18px;
  background: rgba(255, 244, 243, 0.85);
  color: #b42318;
}

.summary-grid,
.metric-grid,
.tasks-layout {
  display: grid;
  gap: 14px;
}

.summary-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-grid {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.tasks-layout {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.summary-card,
.metric-card {
  padding: 18px 20px;
}

.summary-card span,
.metric-card span {
  color: var(--text-secondary);
  font-size: 13px;
}

.summary-card strong,
.metric-card strong {
  display: block;
  margin-top: 10px;
  font-size: 1.9rem;
  line-height: 1;
}

.summary-card small,
.metric-card small,
.panel-note {
  display: block;
  margin-top: 8px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.panel {
  padding: 20px;
}

.panel-head {
  margin-bottom: 12px;
}

.panel-head h3 {
  font-size: 1rem;
}

.panel-head p {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 14px;
}

.task-list,
.checkpoint-list,
.trace-list {
  display: grid;
  gap: 10px;
}

.task-row,
.checkpoint-row,
.trace-row {
  padding: 16px 18px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.36);
}

.task-main {
  min-width: 0;
  flex: 1;
}

.task-line strong,
.checkpoint-row strong {
  color: var(--text-primary);
}

.task-meta {
  margin-top: 8px;
  flex-wrap: wrap;
  color: var(--text-secondary);
  font-size: 13px;
}

.task-side,
.checkpoint-side {
  flex-direction: column;
  align-items: flex-end;
  color: var(--text-tertiary);
  font-size: 12px;
}

.task-error {
  margin-top: 10px;
  color: #b42318;
  font-size: 13px;
}

.trace-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.trace-input {
  flex: 1;
}

.trace-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.trace-seq {
  width: 32px;
  min-width: 32px;
  height: 32px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--color-primary-soft);
  color: var(--color-primary-hover);
  font-size: 12px;
  font-weight: 700;
}

.trace-main {
  min-width: 0;
  flex: 1;
}

.trace-message {
  margin-top: 10px;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.checkpoint-row p {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 13px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid var(--border-color-subtle);
  background: rgba(255, 255, 255, 0.46);
  color: var(--text-secondary);
}

.status-pill[data-status="running"],
.status-pill[data-status="parsing"],
.status-pill[data-status="chunking"],
.status-pill[data-status="indexing"],
.status-pill[data-status="retrying"] {
  color: #0f766e;
  border-color: rgba(15, 118, 110, 0.2);
}

.status-pill[data-status="completed"],
.status-pill[data-status="ready"] {
  color: #0f766e;
  border-color: rgba(15, 118, 110, 0.2);
}

.status-pill[data-status="failed"],
.status-pill[data-status="partial_failed"],
.status-pill[data-status="killed"] {
  color: #b42318;
  border-color: rgba(217, 45, 32, 0.22);
  background: rgba(255, 244, 243, 0.76);
}

.empty-text {
  padding: 12px 4px 4px;
  color: var(--text-tertiary);
  font-size: 14px;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .tasks-layout,
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .summary-grid,
  .metric-grid,
  .tasks-layout {
    grid-template-columns: 1fr;
  }

  .tasks-hero,
  .panel-head,
  .task-row,
  .checkpoint-row,
  .trace-row,
  .trace-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .task-side,
  .checkpoint-side {
    align-items: flex-start;
  }
}
</style>

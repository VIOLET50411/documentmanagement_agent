<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="section-header">
        <div>
          <h2>运行排查</h2>
          <p class="inspect-copy">这里用于查看系统在回答问题时做过哪些判断、留下了哪些恢复点，以及单次请求是怎么一步步跑完的。</p>
        </div>
        <div class="action-group"></div>
      </div>

      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.total ?? 0 }}</span><span class="stat-label">总判断次数</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.allow ?? 0 }}</span><span class="stat-label">直接放行</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.ask ?? 0 }}</span><span class="stat-label">需要确认</span></div>
        <div class="stat-card card compact"><span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.decision_counts?.deny ?? 0 }}</span><span class="stat-label">直接拦截</span></div>
      </div>

      <StatusMessage v-if="runtimeStore.error" tone="error" :message="runtimeStore.error" />

      <div class="inspect-grid">
        <section class="inspect-panel">
          <div class="panel-mini-head">
            <h3>按工具看判断情况</h3>
            <p>看系统在不同工具上，更常见的是直接放行、要求确认，还是直接拦截。</p>
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
                <td>{{ row.allow ?? 0 }}</td>
                <td>{{ row.ask ?? 0 }}</td>
                <td>{{ row.deny ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
          <EmptyState v-else title="当前还没有工具判断统计。" />
        </section>

        <section class="inspect-panel">
          <div class="panel-mini-head">
            <h3>恢复点摘要</h3>
            <p>如果一条请求中断了，可以从这些恢复点继续往下跑。</p>
          </div>
          <div v-if="runtimeStore.checkpointSummary.length" class="checkpoint-list">
            <article v-for="row in runtimeStore.checkpointSummary" :key="row.session_id" class="checkpoint-card">
              <div class="checkpoint-head">
                <strong>{{ row.session_id }}</strong>
                <span class="badge badge-primary">{{ row.resumable ? "可以继续" : "暂不可继续" }}</span>
              </div>
              <p class="checkpoint-meta">停在步骤：{{ checkpointNodeLabel(row.latest_node_name) }} | 第 {{ row.latest_iteration ?? 0 }} 轮</p>
              <p class="checkpoint-meta">系统理解：{{ row.intent || "-" }}</p>
              <p class="checkpoint-meta">检索用语：{{ row.rewritten_query || "-" }}</p>
              <p class="checkpoint-meta">最近时间：{{ formatDate(row.latest_at) }}</p>
            </article>
          </div>
          <EmptyState v-else title="当前还没有恢复点信息。" />
        </section>
      </div>

      <section class="trace-panel">
        <div class="panel-mini-head">
          <h3>单次运行回放</h3>
          <p>输入一条运行记录编号后，可以按时间顺序回看这次请求经历了哪些步骤。</p>
        </div>

        <div class="trace-toolbar">
          <input v-model="runtimeStore.replayTraceId" class="input" type="text" placeholder="请输入运行记录编号 trace_id" />
          <button class="btn btn-primary" @click="runtimeStore.loadReplay()" :disabled="runtimeStore.loadingReplay">
            {{ runtimeStore.loadingReplay ? "加载中..." : "查看这次运行" }}
          </button>
        </div>

        <div v-if="runtimeStore.replayEvents.length" class="trace-list">
          <article v-for="(event, index) in runtimeStore.replayEvents" :key="`${event.event_id || event.sequence_num || index}`" class="trace-row">
            <div class="trace-seq">{{ event.sequence_num ?? index + 1 }}</div>
            <div class="trace-main">
              <div class="trace-head">
                <strong>{{ traceStatusLabel(event.status || event.type) }}</strong>
                <span class="badge badge-secondary">{{ traceSourceLabel(event.source) }}</span>
              </div>
              <p class="trace-meta">
                <span>事件 ID：{{ event.event_id || "-" }}</span>
                <span>运行编号：{{ event.trace_id || runtimeStore.replayTraceId }}</span>
                <span v-if="event.degraded">这一步走了备用路径</span>
              </p>
              <p class="trace-message">{{ traceMessageLabel(event) }}</p>
            </div>
            <div class="trace-time">{{ formatDate(event.timestamp || event.created_at) }}</div>
          </article>
        </div>
        <EmptyState v-else title="输入运行记录编号后，就能查看完整过程。" description="适合排查某一次回答为什么会变成现在这样。" />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from "vue"
import EmptyState from "@/components/common/EmptyState.vue"
import StatusMessage from "@/components/common/StatusMessage.vue"
import { useRuntimeStore } from "@/stores/runtime"
import { checkpointNodeLabel, traceSourceLabel, traceStatusLabel } from "@/utils/adminUi"

const runtimeStore = useRuntimeStore()
let timer: number

defineProps<{
  formatDate: (value?: string | null) => string
}>()

onMounted(async () => {
  if (!runtimeStore.toolDecisionSummary) {
    await runtimeStore.loadToolDecisionSummary()
  }
  if (!runtimeStore.checkpointSummary.length) {
    await runtimeStore.loadCheckpointSummary()
  }
  timer = window.setInterval(() => {
    runtimeStore.loadToolDecisionSummary()
    runtimeStore.loadCheckpointSummary()
  }, 10000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})

function traceMessageLabel(event: Record<string, any>) {
  const message = event.message || event.msg || event.answer || event.content
  if (message) return message
  if (event.degraded && event.fallback_reason) {
    return `已触发降级处理：${event.fallback_reason}`
  }
  return "这一步没有额外说明。"
}
</script>

<style scoped>
.inspect-copy {
  color: var(--text-secondary);
  margin-top: 8px;
}

.inspect-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
  margin-top: var(--space-6);
}

.inspect-panel,
.trace-panel {
  border: 1px solid var(--border-color);
  border-radius: 24px;
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent);
  padding: var(--space-5);
}

.trace-panel {
  margin-top: var(--space-6);
}

.panel-mini-head h3 {
  margin-bottom: 6px;
}

.panel-mini-head p,
.checkpoint-meta,
.trace-meta,
.trace-time,
.trace-message {
  color: var(--text-secondary);
}

.checkpoint-list,
.trace-list {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.checkpoint-card,
.trace-row {
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.34);
  border: 1px solid var(--border-color-subtle);
}

.checkpoint-head,
.trace-head,
.trace-toolbar,
.trace-row {
  display: flex;
  gap: 12px;
}

.checkpoint-head,
.trace-head {
  align-items: center;
  justify-content: space-between;
}

.trace-toolbar {
  margin-top: 16px;
  align-items: center;
}

.trace-row {
  align-items: flex-start;
}

.trace-seq {
  width: 32px;
  min-width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: var(--color-primary-soft);
  color: var(--color-primary-hover);
  font-size: 12px;
  font-weight: 700;
}

.trace-main {
  flex: 1;
  min-width: 0;
}

.trace-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  font-size: 12px;
}

.trace-message {
  margin-top: 10px;
  white-space: pre-wrap;
  word-break: break-word;
}

.trace-time {
  min-width: 140px;
  text-align: right;
  font-size: 12px;
}

@media (max-width: 900px) {
  .inspect-grid {
    grid-template-columns: 1fr;
  }

  .trace-toolbar,
  .trace-row {
    flex-direction: column;
    align-items: stretch;
  }

  .trace-time {
    min-width: 0;
    text-align: left;
  }
}
</style>

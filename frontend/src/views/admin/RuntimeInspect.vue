<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="section-header">
        <div>
          <h2>运行检查台</h2>
          <p class="inspect-copy">把工具决策、检查点恢复和轨迹回放集中在一个视图里，便于排查请求链路、降级点和失败原因。</p>
        </div>
        <div class="action-group">
          <button class="refresh-btn" @click="runtimeStore.loadToolDecisionSummary()" :disabled="runtimeStore.loadingToolSummary">
            {{ runtimeStore.loadingToolSummary ? '加载中...' : '刷新工具统计' }}
          </button>
          <button class="refresh-btn" @click="runtimeStore.loadCheckpointSummary()" :disabled="runtimeStore.loadingCheckpointSummary">
            {{ runtimeStore.loadingCheckpointSummary ? '加载中...' : '刷新检查点' }}
          </button>
        </div>
      </div>

      <div class="stats-grid pipeline-grid">
        <div class="stat-card card compact">
          <span class="stat-value small">{{ runtimeStore.toolDecisionSummary?.total ?? 0 }}</span>
          <span class="stat-label">决策总数</span>
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

      <div v-if="runtimeStore.error" class="inspect-error">
        {{ runtimeStore.error }}
      </div>

      <div class="inspect-grid">
        <section class="inspect-panel">
          <div class="panel-mini-head">
            <h3>按工具统计</h3>
            <p>按工具查看 allow / ask / deny 的分布情况。</p>
          </div>
          <table v-if="runtimeStore.toolMatrixRows.length" class="data-table">
            <thead>
              <tr>
                <th>工具</th>
                <th>allow</th>
                <th>ask</th>
                <th>deny</th>
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
          <p v-else class="empty-text">暂无工具决策统计。</p>
        </section>

        <section class="inspect-panel">
          <div class="panel-mini-head">
            <h3>检查点恢复摘要</h3>
            <p>查看最近可恢复的会话节点、意图和改写查询。</p>
          </div>
          <div v-if="runtimeStore.checkpointSummary.length" class="checkpoint-list">
            <article v-for="row in runtimeStore.checkpointSummary" :key="row.session_id" class="checkpoint-card">
              <div class="checkpoint-head">
                <strong>{{ row.session_id }}</strong>
                <span class="badge badge-primary">{{ row.resumable ? '可恢复' : '待补齐' }}</span>
              </div>
              <p class="checkpoint-meta">节点：{{ row.latest_node_name || '-' }} | 迭代 {{ row.latest_iteration ?? 0 }}</p>
              <p class="checkpoint-meta">意图：{{ row.intent || '-' }}</p>
              <p class="checkpoint-meta">改写查询：{{ row.rewritten_query || '-' }}</p>
              <p class="checkpoint-meta">时间：{{ formatDate(row.latest_at) }}</p>
            </article>
          </div>
          <p v-else class="empty-text">暂无检查点摘要。</p>
        </section>
      </div>

      <section class="trace-panel">
        <div class="panel-mini-head">
          <h3>轨迹回放</h3>
          <p>输入 `trace_id` 后回放单次运行的完整事件流。</p>
        </div>

        <div class="trace-toolbar">
          <input v-model="runtimeStore.replayTraceId" class="input" type="text" placeholder="请输入 trace_id" />
          <button class="btn btn-primary" @click="runtimeStore.loadReplay()" :disabled="runtimeStore.loadingReplay">
            {{ runtimeStore.loadingReplay ? '回放中...' : '回放轨迹' }}
          </button>
        </div>

        <div v-if="runtimeStore.replayEvents.length" class="trace-list">
          <article v-for="(event, index) in runtimeStore.replayEvents" :key="`${event.event_id || event.sequence_num || index}`" class="trace-row">
            <div class="trace-seq">{{ event.sequence_num ?? index + 1 }}</div>
            <div class="trace-main">
              <div class="trace-head">
                <strong>{{ traceStatusLabel(event.status || event.type) }}</strong>
                <span class="badge badge-secondary">{{ event.source || 'runtime' }}</span>
              </div>
              <p class="trace-meta">
                <span>event_id：{{ event.event_id || '-' }}</span>
                <span>trace：{{ event.trace_id || runtimeStore.replayTraceId }}</span>
                <span v-if="event.degraded">已降级</span>
              </p>
              <p class="trace-message">{{ event.message || event.msg || event.answer || event.content || '无附加内容' }}</p>
            </div>
            <div class="trace-time">{{ formatDate(event.timestamp || event.created_at) }}</div>
          </article>
        </div>
        <p v-else class="empty-text">输入 trace_id 后可查看完整运行轨迹。</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue"
import { useRuntimeStore } from "@/stores/runtime"

defineProps<{
  formatDate: (value?: string | null) => string
}>()

const runtimeStore = useRuntimeStore()

onMounted(async () => {
  if (!runtimeStore.toolDecisionSummary) {
    await runtimeStore.loadToolDecisionSummary()
  }
  if (!runtimeStore.checkpointSummary.length) {
    await runtimeStore.loadCheckpointSummary()
  }
})

function traceStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    thinking: "问题理解",
    searching: "知识检索",
    reading: "证据读取",
    tool_call: "工具调用",
    streaming: "回答生成",
    done: "完成",
    error: "失败",
  }
  return labels[status || ""] || (status || "运行事件")
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

.inspect-error {
  margin-top: var(--space-4);
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(198, 40, 40, 0.18);
  background: rgba(198, 40, 40, 0.08);
  color: #b3261e;
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

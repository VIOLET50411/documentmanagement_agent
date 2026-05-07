<template>
  <div class="tasks-page workbench-page">
    <div class="page-toolbar">
      <div class="toolbar-left">
        <h2>任务中心</h2>
      </div>
      <div class="toolbar-actions">
      </div>
    </div>

    <p v-if="tasksStore.error" class="error-banner">{{ tasksStore.error }}</p>

    <!-- Tab Navigation -->
    <nav class="tasks-nav card">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'runtime' }"
        @click="activeTab = 'runtime'"
      >
        运行时态 (Runtime)
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'pipeline' }"
        @click="activeTab = 'pipeline'"
      >
        文档入库
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'training' }"
        @click="activeTab = 'training'"
      >
        模型训练
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'trace' }"
        @click="activeTab = 'trace'"
      >
        轨迹回放定位
      </button>
    </nav>

    <!-- TAB: RUNTIME -->
    <div v-if="activeTab === 'runtime'" class="tab-content fade-in">
      <section class="metric-grid">
        <article class="metric-card card">
          <span>TTFT P95</span>
          <strong
            >{{
              tasksStore.runtimeMetrics?.summary?.ttft_ms_p95 ?? "-"
            }}
            ms</strong
          >
        </article>
        <article class="metric-card card">
          <span>完成耗时 P95</span>
          <strong
            >{{
              tasksStore.runtimeMetrics?.summary?.completion_ms_p95 ?? "-"
            }}
            ms</strong
          >
        </article>
        <article class="metric-card card">
          <span>回退率</span>
          <strong>{{
            percent(tasksStore.runtimeMetrics?.summary?.fallback_rate)
          }}</strong>
        </article>
        <article class="metric-card card">
          <span>工具拒绝率</span>
          <strong>{{
            percent(tasksStore.runtimeMetrics?.summary?.deny_rate)
          }}</strong>
        </article>
        <article class="metric-card card">
          <span>平均工具调用</span>
          <strong>{{
            tasksStore.runtimeMetrics?.summary?.avg_tool_calls ?? "-"
          }}</strong>
        </article>
        <article class="metric-card card">
          <span>SSE 断连</span>
          <strong>{{
            tasksStore.runtimeMetrics?.summary?.sse_disconnects ?? 0
          }}</strong>
        </article>
      </section>

      <div class="tasks-layout">
        <section class="panel card">
          <div class="panel-head">
            <div>
              <h3>运行时任务</h3>
              <p>标准问答与智能体调度任务的底层执行状态。</p>
            </div>
          </div>
          <div class="task-list">
            <article
              v-for="item in tasksStore.runtimeTasks"
              :key="item.task_id"
              class="task-row"
            >
              <div class="task-main">
                <div class="task-line">
                  <strong>{{
                    item.description || item.type || "运行任务"
                  }}</strong>
                  <span class="status-pill" :data-status="item.status">{{
                    unifiedStatusLabel(item.status)
                  }}</span>
                </div>
                <div class="task-meta">
                  <span>类型：{{ item.type || "-" }}</span>
                  <span>Trace ID：{{ item.trace_id || "-" }}</span>
                  <span>重试：{{ item.retries ?? 0 }}</span>
                </div>
              </div>
              <div class="task-actions">
                <button
                  class="btn btn-ghost btn-sm"
                  v-if="item.trace_id"
                  @click="jumpToTrace(item.trace_id)"
                >
                  回放
                </button>
                <button
                  class="btn btn-ghost btn-sm"
                  v-if="item.trace_id"
                  @click="copyText(item.trace_id)"
                >
                  复制 Trace
                </button>
                <span>{{
                  formatTime(
                    item.updated_at || item.end_time || item.start_time,
                  )
                }}</span>
              </div>
            </article>
            <p v-if="tasksStore.runtimeTasks.length === 0" class="empty-text">
              最近没有 Runtime 任务。
            </p>
          </div>
        </section>

        <section class="panel card">
          <div class="panel-head">
            <div>
              <h3>运行检查点摘要</h3>
              <p>可用于恢复多轮长会话和中断前的运行状态。</p>
            </div>
            <span class="panel-note"
              >共 {{ resumableCheckpointCount }} 个可恢复点</span
            >
          </div>
          <div class="checkpoint-list">
            <article
              v-for="item in tasksStore.checkpointSummary"
              :key="item.session_id"
              class="checkpoint-row"
            >
              <div>
                <strong>会话：{{ item.session_id }}</strong>
                <p>
                  节点：{{ item.latest_node_name }} | 迭代
                  {{ item.latest_iteration }}
                </p>
              </div>
              <div class="checkpoint-side">
                <div class="checkpoint-badge" :class="item.resumable ? 'badge-success' : 'badge-error'">
                  <svg v-if="item.resumable" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                  <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                  <span>{{ item.resumable ? "支持恢复" : "状态过期" }}</span>
                </div>
                <small class="checkpoint-time">{{ formatTime(item.latest_at) }}</small>
              </div>
            </article>
            <p
              v-if="tasksStore.checkpointSummary.length === 0"
              class="empty-text"
            >
              暂无运行时检查点摘要。
            </p>
          </div>
        </section>
      </div>
    </div>

    <!-- TAB: PIPELINE -->
    <div v-if="activeTab === 'pipeline'" class="tab-content fade-in">
      <section class="summary-grid">
        <article class="summary-card card">
          <span>活动入库任务</span>
          <strong>{{ activePipelineJobs.length }}</strong>
          <small>解析、分块、索引等全链路状态</small>
        </article>
      </section>

      <section class="panel card">
        <div class="panel-head">
          <div>
            <h3>文档入库任务概览</h3>
            <p>这里展示所有处于流转中或失败异常的文档解析任务。</p>
          </div>
          <button
            class="btn btn-secondary btn-sm"
            @click="$router.push('/documents')"
          >
            跳转文档工作台处理
          </button>
        </div>
        <div class="task-list full-width-list">
          <article
            v-for="item in activePipelineJobs"
            :key="item.doc_id"
            class="task-row"
          >
            <div class="task-main">
              <div class="task-line">
                <strong>{{ item.title || item.doc_id }}</strong>
                <span class="status-pill" :data-status="item.status">{{
                  unifiedStatusLabel(item.status)
                }}</span>
              </div>
              <div class="task-meta">
                <span>进度：{{ item.percentage ?? 0 }}%</span>
                <span>尝试：{{ item.attempt ?? 0 }}</span>
                <span v-if="item.detail">{{ item.detail }}</span>
              </div>
              <p v-if="item.error_message" class="task-error">
                {{ item.error_message }}
              </p>
            </div>
            <div class="task-actions">
              <button class="btn btn-ghost btn-sm" @click="$router.push('/documents')">查看详情</button>
              <span>{{ formatTime(item.updated_at) }}</span>
            </div>
          </article>
          <p v-if="activePipelineJobs.length === 0" class="empty-text">
            当前没有活动中的文档处理任务。
          </p>
        </div>
      </section>
    </div>

    <!-- TAB: TRAINING -->
    <div v-if="activeTab === 'training'" class="tab-content fade-in">
      <section class="deployment-grid">
        <article class="deployment-card card">
          <span>已发布模型</span>
          <strong>{{
            tasksStore.deploymentSummary?.publish_counts?.published ?? 0
          }}</strong>
        </article>
        <article class="deployment-card card">
          <span>发布异常</span>
          <strong>{{
            tasksStore.deploymentSummary?.publish_counts?.failed ?? 0
          }}</strong>
        </article>
        <article class="deployment-card card">
          <span>校验通过</span>
          <strong>{{
            tasksStore.deploymentSummary?.verify_counts?.verified ?? 0
          }}</strong>
        </article>
        <article class="deployment-card card">
          <span>支持回滚</span>
          <strong>{{
            tasksStore.deploymentSummary?.can_rollback ? "是" : "否"
          }}</strong>
        </article>
      </section>

      <div class="tasks-layout">
        <section class="panel card">
          <div class="panel-head">
            <div>
              <h3>模型训练作业</h3>
              <p>数据导出、微调与产物注册任务。</p>
            </div>
            <button
              class="btn btn-secondary btn-sm"
              @click="$router.push('/admin')"
            >
              去管理台查看
            </button>
          </div>
          <div class="task-list">
            <article
              v-for="item in tasksStore.trainingJobs"
              :key="item.id"
              class="task-row"
            >
              <div class="task-main">
                <div class="task-line">
                  <strong>{{
                    item.target_model_name || item.dataset_name || item.id
                  }}</strong>
                  <span class="status-pill" :data-status="item.status">{{
                    unifiedStatusLabel(item.status)
                  }}</span>
                </div>
                <div class="task-meta">
                  <span>阶段：{{ item.stage || "-" }}</span>
                  <span>渠道：{{ item.provider || "-" }}</span>
                  <span
                    >样本：{{ item.train_records ?? 0 }}/{{
                      item.val_records ?? 0
                    }}</span
                  >
                </div>
                <p v-if="item.error_message" class="task-error">
                  {{ item.error_message }}
                </p>
              </div>
              <div class="task-actions">
                <button class="btn btn-ghost btn-sm" @click="$router.push('/admin?tab=evaluation')">模型治理</button>
                <span>{{
                  formatTime(item.updated_at || item.created_at)
                }}</span>
              </div>
            </article>
            <p v-if="tasksStore.trainingJobs.length === 0" class="empty-text">
              当前没有训练任务记录。
            </p>
          </div>
        </section>

        <section class="panel card">
          <div class="panel-head">
            <div>
              <h3>部署异常诊断</h3>
              <p>最近的服务端模型加载、健康探针异常情况。</p>
            </div>
          </div>
          <div class="task-list">
            <article
              v-for="item in recentDeploymentFailures"
              :key="item.model_id"
              class="task-row"
            >
              <div class="task-main">
                <div class="task-line">
                  <strong>{{ item.model_name }}</strong>
                  <span class="status-pill" data-status="failed">{{
                    item.failure_category
                  }}</span>
                </div>
                <div class="task-meta">
                  <span>状态：{{ unifiedStatusLabel(item.status) }}</span>
                  <span>可恢复：{{ item.recoverable ? "是" : "否" }}</span>
                </div>
                <p class="trace-message">
                  {{
                    item.recommended_action ||
                    item.publish_reason ||
                    item.verify_reason ||
                    "暂无更多信息"
                  }}
                </p>
              </div>
              <div class="task-actions">
                <button class="btn btn-ghost btn-sm" @click="$router.push('/admin?tab=backends')">排查节点</button>
                <span>{{ formatTime(item.updated_at) }}</span>
              </div>
            </article>
            <p v-if="recentDeploymentFailures.length === 0" class="empty-text">
              无最近部署失败记录。
            </p>
          </div>
        </section>
      </div>
    </div>

    <!-- TAB: TRACE REPLAY -->
    <div v-if="activeTab === 'trace'" class="tab-content fade-in">
      <section class="panel card" style="min-height: 500px">
        <div class="panel-head">
          <div>
            <h3>底层运行轨迹定位 (Trace Replay)</h3>
            <p>
              输入 `trace_id`
              获取智能体底层的检索、工具调用、思考链路，用于排查降级和截断。
            </p>
          </div>
        </div>

        <div class="trace-toolbar">
          <input
            v-model="traceInput"
            class="input trace-input"
            type="text"
            placeholder="请输入完整的 trace_id..."
            @keyup.enter="handleTraceReplay"
          />
          <button
            class="btn btn-primary"
            :disabled="tasksStore.replayingTrace || !traceInput.trim()"
            @click="handleTraceReplay"
          >
            {{ tasksStore.replayingTrace ? "检索并回放..." : "拉取轨迹" }}
          </button>
        </div>

        <div
          v-if="tasksStore.traceError"
          class="task-error"
          style="margin-bottom: 24px"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          {{ tasksStore.traceError }}
        </div>

        <!-- 轨迹内容展示区 -->
        <div class="trace-content-area" v-if="tasksStore.traceEvents.length">
          <div class="trace-header">
            <h4>当前回放链路：{{ traceInput }}</h4>
            <button class="btn btn-ghost btn-sm" @click="copyTraceId">
              复制 ID
            </button>
          </div>

          <div class="trace-list">
            <article
              v-for="(event, index) in tasksStore.traceEvents"
              :key="`${event.event_id || event.sequence_num || index}`"
              class="trace-row"
            >
              <div class="trace-seq">{{ event.sequence_num ?? index + 1 }}</div>
              <div class="trace-main">
                <div class="task-line">
                  <strong>{{
                    unifiedStatusLabel(event.status || event.type)
                  }}</strong>
                  <span
                    class="status-pill"
                    :data-status="event.status || event.type"
                    >{{ event.source || "runtime" }}</span
                  >
                </div>
                <div class="task-meta">
                  <span v-if="event.event_id"
                    >Event ID：{{ event.event_id }}</span
                  >
                  <span v-if="event.fallback_reason"
                    >降级原因：{{ event.fallback_reason }}</span
                  >
                </div>
                <p class="trace-message">
                  {{
                    event.message ||
                    event.msg ||
                    event.answer ||
                    event.content ||
                    "无附加报文"
                  }}
                </p>
              </div>
              <div class="task-side">
                <span>{{
                  formatTime(event.timestamp || event.created_at)
                }}</span>
                <small :class="{ 'text-danger': event.degraded }">{{
                  event.degraded ? "已触发降级" : "正常执行"
                }}</small>
              </div>
            </article>
          </div>
        </div>

        <!-- 空态提示 -->
        <div
          class="empty-trace-state"
          v-else-if="!tasksStore.traceError && !tasksStore.replayingTrace"
        >
          <div class="empty-icon">
            <svg
              width="48"
              height="48"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            </svg>
          </div>
          <h4>准备回放</h4>
          <p>请在上方输入来源任务的 Trace ID 以定位内部执行细节。</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useTasksStore } from "@/stores/tasks";

const router = useRouter();
const tasksStore = useTasksStore();
const activeTab = ref("runtime");
const traceInput = ref("");

const activePipelineJobs = computed(() =>
  tasksStore.pipelineJobs.filter((item) =>
    [
      "queued",
      "parsing",
      "chunking",
      "indexing",
      "retrying",
      "failed",
      "partial_failed",
    ].includes(item.status),
  ),
);

const resumableCheckpointCount = computed(
  () =>
    tasksStore.checkpointSummary.filter((item) => Boolean(item.resumable))
      .length,
);

const recentDeploymentFailures = computed(
  () => tasksStore.deploymentSummary?.recent_failures || [],
);

let refreshTimer: number | null = null

function handleRefresh() {
  tasksStore.loadDashboard();
}

onMounted(() => {
  handleRefresh()
  refreshTimer = window.setInterval(() => {
    handleRefresh()
  }, 15000)
})

onUnmounted(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
  }
})

async function handleTraceReplay() {
  if (!traceInput.value.trim()) return;
  await tasksStore.replayTrace(traceInput.value.trim());
}

function jumpToTrace(id: string) {
  traceInput.value = id;
  activeTab.value = "trace";
  handleTraceReplay();
}

function copyTraceId() {
  copyText(traceInput.value);
}

function copyText(text: string) {
  if (text) {
    navigator.clipboard
      .writeText(text)
      .then(() => alert("已复制"))
      .catch(() => alert("复制失败"));
  }
}

// Utils
function percent(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatTime(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

// Unified Label Translation Map
function unifiedStatusLabel(status: string | null | undefined) {
  const normalized = (status || "").toLowerCase();
  const map: Record<string, string> = {
    // runtime
    pending: "待执行",
    running: "运行中",
    completed: "已完成",
    failed: "处理失败",
    killed: "已终止",
    // pipeline
    queued: "排队中",
    parsing: "解析中",
    chunking: "切块中",
    indexing: "建立索引",
    retrying: "重试中",
    partial_failed: "部分失败",
    ready: "已入库",
    // training
    training: "训练中",
    validating: "校验中",
    publishing: "发布中",
    published: "已发布",
    verified: "已校验",
    // trace
    thinking: "问题理解",
    searching: "知识检索",
    reading: "证据读取",
    tool_call: "工具调用",
    streaming: "回答生成",
    done: "链路结束",
    error: "链路中断",
  };
  return map[normalized] || status || "未知状态";
}
</script>

<style scoped>
.tasks-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.tasks-nav {
  display: flex;
  gap: 8px;
  padding: 8px;
  overflow-x: auto;
  scrollbar-width: none;
}

.tasks-nav::-webkit-scrollbar {
  display: none;
}

.tab-btn {
  padding: 10px 20px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.tab-btn:hover {
  color: var(--text-primary);
  background: var(--bg-surface-hover);
}

.tab-btn.active {
  background: var(--bg-input);
  color: var(--text-primary);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.tab-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.fade-in {
  animation: fadeIn 0.2s ease-out forwards;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-head,
.task-line,
.task-meta,
.checkpoint-row,
.checkpoint-side,
.trace-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-head,
.checkpoint-row,
.trace-header {
  justify-content: space-between;
}

.error-banner,
.task-error {
  padding: 14px 18px;
  border-radius: 12px;
  background: rgba(217, 45, 32, 0.08);
  border: 1px solid rgba(217, 45, 32, 0.15);
  color: var(--color-danger);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9rem;
}

.task-error {
  margin-top: 10px;
  padding: 10px 14px;
}

.summary-grid,
.metric-grid,
.tasks-layout,
.deployment-grid {
  display: grid;
  gap: 14px;
}

.summary-grid,
.deployment-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-grid {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.tasks-layout {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.summary-card,
.metric-card,
.deployment-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.summary-card span,
.metric-card span,
.deployment-card span {
  color: var(--text-secondary);
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.summary-card strong,
.metric-card strong,
.deployment-card strong {
  display: block;
  margin-top: 12px;
  font-size: 1.8rem;
  line-height: 1.1;
  color: var(--color-primary);
}

.summary-card small,
.metric-card small,
.deployment-card small,
.panel-note {
  display: block;
  margin-top: 8px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.panel {
  padding: 24px;
}

.panel-head {
  margin-bottom: 20px;
}

.panel-head h3 {
  font-size: 1.1rem;
}

.panel-head p {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.task-list,
.checkpoint-list,
.trace-list {
  display: grid;
  gap: 12px;
}

.task-row,
.checkpoint-row,
.trace-row {
  padding: 18px;
  border-radius: 16px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-color-subtle);
  display: flex;
  justify-content: space-between;
}

.task-main {
  min-width: 0;
  flex: 1;
}

.task-line strong,
.checkpoint-row strong {
  color: var(--text-primary);
  font-size: 1rem;
}

.task-meta {
  margin-top: 10px;
  flex-wrap: wrap;
  color: var(--text-secondary);
  font-size: 13px;
}

.task-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  color: var(--text-tertiary);
  font-size: 12px;
  min-width: 120px;
}

.trace-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.trace-input {
  flex: 1;
  max-width: 600px;
}

.trace-header {
  margin-bottom: 16px;
}

.trace-header h4 {
  color: var(--text-secondary);
}

.empty-trace-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: var(--text-tertiary);
}

.empty-icon {
  margin-bottom: 16px;
  color: var(--border-color-strong);
}

.trace-row {
  justify-content: flex-start;
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
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-input);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 0.9rem;
  line-height: 1.6;
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
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--border-color-subtle);
  background: var(--bg-body);
  color: var(--text-secondary);
}

.status-pill[data-status="running"],
.status-pill[data-status="parsing"],
.status-pill[data-status="chunking"],
.status-pill[data-status="indexing"],
.status-pill[data-status="retrying"] {
  color: #0f766e;
  border-color: rgba(15, 118, 110, 0.2);
  background: rgba(15, 118, 110, 0.05);
}

.status-pill[data-status="completed"],
.status-pill[data-status="ready"] {
  color: #0f766e;
  border-color: rgba(15, 118, 110, 0.2);
}

.status-pill[data-status="failed"],
.status-pill[data-status="partial_failed"],
.status-pill[data-status="killed"],
.status-pill[data-status="error"] {
  color: var(--color-danger);
  border-color: rgba(217, 45, 32, 0.2);
  background: rgba(217, 45, 32, 0.05);
}

.empty-text {
  padding: 20px 0;
  color: var(--text-tertiary);
  font-size: 0.9rem;
  text-align: center;
}

.checkpoint-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.checkpoint-badge.badge-success {
  color: var(--color-success);
}

.checkpoint-badge.badge-error {
  color: var(--text-tertiary);
}

.checkpoint-time {
  color: var(--text-tertiary);
  font-size: 12px;
  min-width: 140px;
  text-align: right;
}

.text-danger {
  color: var(--color-danger) !important;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .tasks-layout,
  .summary-grid,
  .deployment-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .tasks-layout,
  .deployment-grid {
    grid-template-columns: 1fr;
  }

  .summary-grid,
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .task-row,
  .checkpoint-row,
  .trace-row {
    flex-direction: column;
    align-items: stretch;
  }

  .task-actions,
  .checkpoint-side,
  .task-side {
    align-items: flex-start;
    margin-top: 12px;
    flex-direction: row;
    gap: 16px;
  }
}

@media (max-width: 480px) {
  .summary-grid,
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>

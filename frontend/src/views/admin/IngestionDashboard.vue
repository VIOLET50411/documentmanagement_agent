<template>
  <div class="tab-content animate-fade-in">
    <div class="stats-grid pipeline-grid">
      <div v-for="item in pipelineCards" :key="item.label" class="stat-card card">
        <span class="stat-value">{{ item.value }}</span>
        <span class="stat-label">{{ item.label }}</span>
      </div>
    </div>

    <div class="card section-card">
      <div class="evaluation-header">
        <div>
          <h2>资料处理任务</h2>
          <p class="report-meta">这里可以查看资料导入、切分、入库的处理情况。</p>
        </div>
        <div class="action-group">
          <button class="btn btn-secondary btn-sm" @click="$router.push('/documents')">去资料库查看</button>
          <button class="btn btn-secondary btn-sm" @click="$router.push('/tasks?tab=pipeline')">去任务中心查看</button>
          <button class="btn btn-danger btn-sm" :disabled="state.retryingFailed" @click="retryFailedJobs">
            {{ state.retryingFailed ? "重试中..." : "一键重试失败任务" }}
          </button>
        </div>
      </div>

      <StatusMessage v-if="state.error" tone="error" :message="state.error" />

      <div class="filters-grid">
        <select v-model="state.pipelineFilterStatus" class="input">
          <option value="">全部状态</option>
          <option value="failed_family">失败或部分失败</option>
          <option value="queued">等待中</option>
          <option value="parsing">解析中</option>
          <option value="chunking">切分中</option>
          <option value="indexing">入库中</option>
          <option value="retrying">重试中</option>
          <option value="ready">已完成</option>
          <option value="partial_failed">部分失败</option>
          <option value="failed">失败</option>
        </select>
        <div></div>
        <div></div>
      </div>

      <table v-if="state.pipelineJobs.length" class="data-table">
        <thead>
          <tr>
            <th>资料</th>
            <th>状态</th>
            <th>进度</th>
            <th>已尝试次数</th>
            <th>当前说明</th>
            <th>最近更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in state.pipelineJobs" :key="job.doc_id">
            <td>{{ job.title }}</td>
            <td>{{ readablePipelineStatus(job.status) }}</td>
            <td>{{ job.percentage }}%</td>
            <td>{{ job.attempt }}</td>
            <td>{{ readableJobDetail(job) }}</td>
            <td>{{ formatDate(job.updated_at) }}</td>
            <td class="action-group">
              <button class="btn btn-ghost" :disabled="!['failed', 'partial_failed', 'retrying'].includes(job.status)" @click="retryPipelineJob(job)">重试</button>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前没有任务数据。" description="如果你刚上传资料，稍等几秒后会出现在这里。" action-label="去资料库查看" @action="$router.push('/documents')" />

      <div class="pagination-row">
        <span class="list-meta">共 {{ state.pipelineTotal }} 条，当前第 {{ state.pipelinePage + 1 }} 页</span>
        <div class="action-group">
          <button class="btn btn-ghost" :disabled="state.pipelinePage === 0 || state.loadingPipeline" @click="changePipelinePage(-1)">上一页</button>
          <button class="btn btn-ghost" :disabled="(state.pipelinePage + 1) * state.pipelinePageSize >= state.pipelineTotal || state.loadingPipeline" @click="changePipelinePage(1)">下一页</button>
        </div>
      </div>

      <h2 class="sub-section-title">失败原因汇总</h2>
      <table v-if="state.pipelineFailureSummary.length" class="data-table">
        <thead>
          <tr>
            <th>错误类型</th>
            <th>数量</th>
            <th>失败分布</th>
            <th>最近出现时间</th>
            <th>示例说明</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in state.pipelineFailureSummary" :key="item.signature">
            <td>
              <div class="failure-title-cell">
                <strong>{{ readableFailureSignature(item.signature) }}</strong>
                <code>{{ item.signature }}</code>
              </div>
            </td>
            <td>{{ item.count }}</td>
            <td>失败 {{ item.status_breakdown?.failed || 0 }} / 部分失败 {{ item.status_breakdown?.partial_failed || 0 }}</td>
            <td>{{ formatDate(item.latest_at) }}</td>
            <td>{{ item.example_error || "暂时没有示例" }}</td>
            <td class="action-group">
              <button class="btn btn-ghost" :disabled="state.retryingSignature === item.signature" @click="retryBySignature(item.signature)">
                {{ state.retryingSignature === item.signature ? "重试中..." : "重试这类任务" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="当前没有汇总到失败原因。" description="说明最近没有明显的批量失败问题。" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue"
import EmptyState from "@/components/common/EmptyState.vue"
import StatusMessage from "@/components/common/StatusMessage.vue"
import { useAdminPipeline } from "./composables/useAdminPipeline"

const {
  state,
  pipelineCards,
  loadPipelineStatus,
  loadPipelineJobs,
  applyPipelineFilter,
  changePipelinePage,
  retryPipelineJob,
  retryFailedJobs,
  retryBySignature,
  formatDate,
  readablePipelineStatus,
  readableJobDetail,
  readableFailureSignature,
} = useAdminPipeline()

let timer: number

onMounted(() => {
  loadPipelineStatus()
  loadPipelineJobs()
  timer = window.setInterval(() => {
    loadPipelineStatus()
    loadPipelineJobs()
  }, 10000)
})

watch(
  () => state.pipelineFilterStatus,
  () => {
    applyPipelineFilter()
  },
)

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.failure-title-cell {
  display: grid;
  gap: 4px;
}

.failure-title-cell strong {
  color: var(--text-primary);
}

.failure-title-cell code {
  color: var(--text-tertiary);
  font-size: 12px;
}
</style>

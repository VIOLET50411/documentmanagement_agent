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
        <h2>最近任务</h2>
        <div class="action-group">
          <button class="btn btn-secondary btn-sm" @click="$router.push('/documents')">前往文档库排查</button>
          <button class="btn btn-secondary btn-sm" @click="$router.push('/tasks?tab=pipeline')">前往任务中心轨迹</button>
          <button class="btn btn-danger btn-sm" :disabled="state.retryingFailed" @click="retryFailedJobs">
            {{ state.retryingFailed ? "重试中..." : "一键重试失败任务" }}
          </button>
        </div>
      </div>

      <div class="filters-grid">
        <select v-model="state.pipelineFilterStatus" class="input">
          <option value="">全部状态</option>
          <option value="failed_family">失败/部分失败</option>
          <option value="queued">queued</option>
          <option value="parsing">parsing</option>
          <option value="chunking">chunking</option>
          <option value="indexing">indexing</option>
          <option value="retrying">retrying</option>
          <option value="ready">ready</option>
          <option value="partial_failed">partial_failed</option>
          <option value="failed">failed</option>
        </select>
        <div></div>
        <div></div>
      </div>

      <table v-if="state.pipelineJobs.length" class="data-table">
        <thead>
          <tr>
            <th>文档</th>
            <th>状态</th>
            <th>进度</th>
            <th>尝试次数</th>
            <th>详情</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in state.pipelineJobs" :key="job.doc_id">
            <td>{{ job.title }}</td>
            <td>{{ job.status }}</td>
            <td>{{ job.percentage }}%</td>
            <td>{{ job.attempt }}</td>
            <td>{{ job.detail || job.error_message || "-" }}</td>
            <td>{{ formatDate(job.updated_at) }}</td>
            <td class="action-group">
              <button
                class="btn btn-ghost"
                :disabled="!['failed', 'partial_failed', 'retrying'].includes(job.status)"
                @click="retryPipelineJob(job)"
              >
                重试
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无任务数据。</p>

      <div class="pagination-row">
        <span class="list-meta">共 {{ state.pipelineTotal }} 条，当前第 {{ state.pipelinePage + 1 }} 页</span>
        <div class="action-group">
          <button class="btn btn-ghost" :disabled="state.pipelinePage === 0 || state.loadingPipeline" @click="changePipelinePage(-1)">上一页</button>
          <button
            class="btn btn-ghost"
            :disabled="(state.pipelinePage + 1) * state.pipelinePageSize >= state.pipelineTotal || state.loadingPipeline"
            @click="changePipelinePage(1)"
          >
            下一页
          </button>
        </div>
      </div>

      <h2 class="sub-section-title">失败原因聚合</h2>
      <table v-if="state.pipelineFailureSummary.length" class="data-table">
        <thead>
          <tr>
            <th>错误签名</th>
            <th>数量</th>
            <th>状态拆分</th>
            <th>最近时间</th>
            <th>示例错误</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in state.pipelineFailureSummary" :key="item.signature">
            <td><code>{{ item.signature }}</code></td>
            <td>{{ item.count }}</td>
            <td>failed: {{ item.status_breakdown?.failed || 0 }} / partial_failed: {{ item.status_breakdown?.partial_failed || 0 }}</td>
            <td>{{ formatDate(item.latest_at) }}</td>
            <td>{{ item.example_error || "-" }}</td>
            <td class="action-group">
              <button class="btn btn-ghost" :disabled="state.retryingSignature === item.signature" @click="retryBySignature(item.signature)">
                {{ state.retryingSignature === item.signature ? "重试中..." : "按此错误重试" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无失败原因聚合数据。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue"
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

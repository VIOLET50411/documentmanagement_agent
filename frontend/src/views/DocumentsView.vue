<template>
  <div class="documents-page workbench-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">文档工作台</p>
        <h1>上传、处理并跟踪文档状态</h1>
        <p class="page-subtitle">这里聚合上传、分片处理、失败重试和最近任务事件。</p>
      </div>
      <div class="header-actions">
        <input v-model="searchQuery" class="input search-input" placeholder="搜索文档" />
        <label class="btn btn-primary upload-btn">
          上传文档
          <input type="file" class="sr-only" multiple accept=".pdf,.docx,.xlsx,.csv,.png,.jpg,.jpeg" @change="handleUpload" />
        </label>
      </div>
    </header>

    <div class="stats-row">
      <div class="stat-card card"><span class="stat-value">{{ documents.length }}</span><span class="stat-label">文档总数</span></div>
      <div class="stat-card card"><span class="stat-value">{{ readyCount }}</span><span class="stat-label">已完成</span></div>
      <div class="stat-card card"><span class="stat-value">{{ processingCount }}</span><span class="stat-label">处理中</span></div>
      <div class="stat-card card"><span class="stat-value">{{ failedCount }}</span><span class="stat-label">失败</span></div>
    </div>

    <div v-if="Object.keys(docStore.uploadProgress).length" class="upload-progress-area">
      <div v-for="(prog, docId) in docStore.uploadProgress" :key="docId" class="progress-item card animate-slide-in">
        <div class="progress-info">
          <span>{{ prog.fileName || `${docId.slice(0, 8)}...` }}</span>
          <span class="badge" :class="statusBadgeClass(prog.status)">{{ progressLabel(prog.status) }}</span>
        </div>
        <div class="progress-bar"><div class="progress-fill" :style="{ width: `${prog.percentage}%` }"></div></div>
      </div>
    </div>

    <div class="documents-table card">
      <table>
        <thead>
          <tr>
            <th>文件名</th>
            <th>类型</th>
            <th>部门</th>
            <th>状态</th>
            <th>进度</th>
            <th>上传时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="doc in filteredDocuments" :key="doc.id" class="doc-row">
            <td class="doc-name"><span class="doc-icon">{{ fileIcon(doc.file_type) }}</span>{{ doc.title }}</td>
            <td><span class="badge badge-primary">{{ doc.file_type?.split('/').pop() || '-' }}</span></td>
            <td>{{ doc.department || '-' }}</td>
            <td><span class="badge" :class="statusBadgeClass(doc.status)">{{ progressLabel(doc.status) }}</span></td>
            <td>{{ doc.percentage ?? docStore.uploadProgress[doc.id]?.percentage ?? 0 }}%</td>
            <td class="text-muted">{{ formatDate(doc.created_at) }}</td>
            <td class="table-actions">
              <button class="btn btn-ghost btn-sm" @click="showEvents(doc.id)">详情</button>
              <button v-if="['failed', 'partial_failed', 'retrying'].includes(doc.status)" class="btn btn-ghost btn-sm" @click="retryDoc(doc.id)">重试</button>
              <button class="btn btn-ghost btn-sm" @click="deleteDoc(doc.id)">删除</button>
            </td>
          </tr>
          <tr v-if="filteredDocuments.length === 0"><td colspan="7" class="empty-table">暂无文档，先上传一个文件开始处理。</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="selectedEvents.length" class="card event-panel">
      <div class="event-panel-header">
        <h3>最近任务事件（{{ selectedDocTitle || '-' }}）</h3>
        <button class="btn btn-ghost btn-sm" @click="selectedEvents = []">关闭</button>
      </div>
      <div class="event-summary">
        <p><strong>当前状态：</strong>{{ progressLabel(selectedDocStatus) }}</p>
        <p><strong>失败摘要：</strong>{{ selectedDocError || '无' }}</p>
        <p v-if="batchFailures.length"><strong>批次失败：</strong>{{ batchFailures.join('；') }}</p>
      </div>
      <ul class="event-list">
        <li v-for="(event, index) in selectedEvents" :key="index">
          <strong>{{ progressLabel(event.status) }}</strong>
          <span>{{ event.detail || '-' }}</span>
          <span class="text-muted">{{ formatDate(event.updated_at) }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { documentsApi } from '@/api/documents'
import { useDocumentStore } from '@/stores/documents'

const docStore = useDocumentStore()
const searchQuery = ref('')
const documents = ref([])
const selectedEvents = ref([])
const selectedDocTitle = ref('')
const selectedDocStatus = ref('unknown')
const selectedDocError = ref('')
const batchFailures = ref([])

const filteredDocuments = computed(() => {
  if (!searchQuery.value) return documents.value
  const q = searchQuery.value.toLowerCase()
  return documents.value.filter((d) => d.title?.toLowerCase().includes(q))
})
const readyCount = computed(() => documents.value.filter((d) => d.status === 'ready').length)
const processingCount = computed(() => documents.value.filter((d) => ['queued', 'uploaded', 'parsing', 'chunking', 'indexing', 'retrying'].includes(d.status)).length)
const failedCount = computed(() => documents.value.filter((d) => ['failed', 'partial_failed'].includes(d.status)).length)

onMounted(loadDocuments)

async function loadDocuments() {
  try {
    const res = await documentsApi.list()
    documents.value = res.documents || []
    docStore.setDocuments(documents.value, res.total || 0)
  } catch {
    documents.value = []
  }
}

async function handleUpload(event) {
  const files = Array.from(event.target.files || [])
  for (const file of files) {
    try {
      const res = await uploadFile(file)
      documents.value.unshift(res)
      docStore.updateUploadProgress(res.id, 'queued', 0, file.name)
      pollStatus(res.id)
    } catch (error) {
      console.error('Upload failed:', error)
    }
  }
  event.target.value = ''
}

async function uploadFile(file) {
  const chunkThreshold = 8 * 1024 * 1024
  const chunkSize = 2 * 1024 * 1024

  if (file.size <= chunkThreshold) {
    const direct = await documentsApi.upload(file)
    return direct
  }

  const uploadKey = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const totalParts = Math.ceil(file.size / chunkSize)
  docStore.updateUploadProgress(uploadKey, 'uploading', 0, file.name)

  const session = await documentsApi.createUploadSession({
    file_name: file.name,
    content_type: file.type || 'application/octet-stream',
    file_size: file.size,
    total_parts: totalParts,
  })

  for (let index = 0; index < totalParts; index += 1) {
    const start = index * chunkSize
    const end = Math.min(file.size, start + chunkSize)
    const blob = file.slice(start, end)
    const partNumber = index + 1
    await documentsApi.uploadChunk(session.upload_id, partNumber, totalParts, blob)
    const percentage = Math.min(95, Math.round((partNumber / totalParts) * 100))
    docStore.updateUploadProgress(uploadKey, 'uploading', percentage, file.name)
  }

  const completed = await documentsApi.completeUpload(session.upload_id)
  docStore.clearUploadProgress(uploadKey)
  return completed
}

function pollStatus(docId) {
  const interval = setInterval(async () => {
    try {
      const status = await documentsApi.getStatus(docId)
      docStore.updateUploadProgress(docId, status.status, parseInt(status.percentage, 10) || 0)
      const target = documents.value.find((d) => d.id === docId)
      if (target) {
        target.status = status.status
        target.percentage = parseInt(status.percentage, 10) || 0
        target.error_message = status.error_message
      }
      if (['ready', 'failed', 'partial_failed'].includes(status.status)) {
        clearInterval(interval)
        if (status.status === 'ready') {
          setTimeout(() => docStore.clearUploadProgress(docId), 1500)
        }
      }
    } catch {
      clearInterval(interval)
    }
  }, 2000)
}

async function retryDoc(docId) {
  await documentsApi.retry(docId)
  const target = documents.value.find((d) => d.id === docId)
  if (target) {
    target.status = 'queued'
    target.percentage = 0
  }
  pollStatus(docId)
}

async function showEvents(docId) {
  const [eventsRes, statusRes] = await Promise.all([documentsApi.getEvents(docId), documentsApi.getStatus(docId)])
  selectedEvents.value = eventsRes.events || []
  selectedDocStatus.value = statusRes.status || 'unknown'
  selectedDocError.value = statusRes.error_message || ''
  const target = documents.value.find((d) => d.id === docId)
  selectedDocTitle.value = target?.title || docId
  batchFailures.value = extractBatchFailures(selectedEvents.value, selectedDocError.value)
}

async function deleteDoc(docId) {
  if (!confirm('确定删除这个文档吗？')) return
  try {
    await documentsApi.delete(docId)
    documents.value = documents.value.filter((d) => d.id !== docId)
  } catch (error) {
    console.error('Delete failed:', error)
  }
}

function fileIcon(type) {
  if (!type) return 'DOC'
  if (type.includes('pdf')) return 'PDF'
  if (type.includes('word') || type.includes('docx')) return 'DOC'
  if (type.includes('excel') || type.includes('xlsx')) return 'XLS'
  if (type.includes('csv')) return 'CSV'
  if (type.includes('image')) return 'IMG'
  return 'DOC'
}

function statusBadgeClass(status) {
  const map = { uploading: 'badge-warning', ready: 'badge-success', queued: 'badge-warning', uploaded: 'badge-warning', parsing: 'badge-warning', chunking: 'badge-warning', indexing: 'badge-warning', retrying: 'badge-warning', failed: 'badge-danger', partial_failed: 'badge-danger' }
  return map[status] || 'badge-primary'
}

function progressLabel(status) {
  const labels = { uploading: '上传中', uploaded: '已上传', queued: '排队中', parsing: '解析中', chunking: '分块中', indexing: '建索引中', retrying: '重试中', ready: '已完成', failed: '失败', partial_failed: '部分失败', unknown: '未知' }
  return labels[status] || status || '未知'
}

function formatDate(date) {
  return date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-'
}

function extractBatchFailures(events, errorMessage) {
  const content = [errorMessage, ...events.map((e) => e.error), ...events.map((e) => e.detail)]
    .filter(Boolean)
    .join('；')
  const matches = content.match(/第\d+批失败[^；]*/g) || []
  return [...new Set(matches)]
}
</script>

<style scoped>
.workbench-page {
  padding: 0 12px 12px;
  overflow-y: auto;
  height: 100%;
}

.page-header {
  max-width: 1240px;
  margin: 0 auto 18px;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--space-4);
}

.page-kicker {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
}

.page-header h1 {
  font-size: clamp(1.8rem, 3vw, 2.6rem);
  line-height: 1.08;
  margin-top: 6px;
}

.page-subtitle {
  color: var(--text-secondary);
  font-size: 1rem;
  margin-top: 10px;
}

.header-actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}

.search-input {
  min-width: 220px;
}

.stats-row {
  max-width: 1240px;
  margin: 0 auto 16px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 120px;
  justify-content: center;
}

.stat-value {
  font-size: clamp(2rem, 4vw, 2.6rem);
  line-height: 1;
}

.stat-label {
  color: var(--text-secondary);
}

.upload-progress-area,
.documents-table,
.event-panel {
  max-width: 1240px;
  margin: 0 auto 16px;
}

.upload-progress-area {
  display: grid;
  gap: 12px;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: 10px;
}

.progress-bar {
  width: 100%;
  height: 10px;
  border-radius: 999px;
  background: var(--bg-input);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--color-primary), #dfb17d);
}

.documents-table {
  overflow: hidden;
}

.documents-table table {
  width: 100%;
  border-collapse: collapse;
}

.documents-table th,
.documents-table td {
  padding: 14px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border-color-subtle);
  vertical-align: middle;
}

.documents-table th {
  font-size: 0.76rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
}

.doc-name {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
}

.doc-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: var(--bg-input);
  font-size: 0.74rem;
  font-weight: 700;
}

.text-muted {
  color: var(--text-tertiary);
}

.table-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.empty-table {
  text-align: center;
  color: var(--text-secondary);
}

.event-panel-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: center;
  margin-bottom: var(--space-4);
}

.event-summary {
  display: grid;
  gap: 6px;
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
}

.event-list {
  display: grid;
  gap: 10px;
}

.event-list li {
  list-style: none;
  display: grid;
  gap: 6px;
  padding: 14px 0;
  border-top: 1px solid var(--border-color-subtle);
}

@media (max-width: 1000px) {
  .stats-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .workbench-page {
    padding: 0 0 12px;
  }

  .page-header,
  .header-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .stats-row {
    grid-template-columns: 1fr;
  }

  .documents-table {
    overflow-x: auto;
  }
}
</style>

<template>
  <div
    class="documents-page workbench-page"
    :class="{ 'drawer-open': !!selectedDocForDetails }"
  >
    <div class="page-toolbar">
      <div class="toolbar-left">
        <h2>文档工作台</h2>
      </div>
      <div class="toolbar-actions">
        <label class="btn btn-primary upload-btn">
          上传文档
          <input
            type="file"
            class="sr-only"
            multiple
            accept=".pdf,.docx,.xlsx,.csv,.png,.jpg,.jpeg"
            @change="handleUpload"
          />
        </label>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card card">
        <span class="stat-value">{{ total }}</span
        ><span class="stat-label">文档总数</span>
      </div>
      <div class="stat-card card">
        <span class="stat-value">{{ readyCount }}</span
        ><span class="stat-label">已完成</span>
      </div>
      <div class="stat-card card">
        <span class="stat-value">{{ processingCount }}</span
        ><span class="stat-label">处理中</span>
      </div>
      <div class="stat-card card">
        <span class="stat-value">{{ failedCount }}</span
        ><span class="stat-label">异常与失败</span>
      </div>
    </div>

    <!-- 过滤器与批量操作区 -->
    <div class="filter-bar card">
      <div class="filter-group">
        <input
          v-model="filters.query"
          class="input search-input"
          placeholder="搜索文档标题..."
          @keyup.enter="fetchDocuments"
        />

        <div class="filter-chips">
          <button
            class="chip"
            :class="{ active: filters.status === '' }"
            @click="
              filters.status = '';
              fetchDocuments();
            "
          >
            全部
          </button>
          <button
            class="chip"
            :class="{ active: filters.status === 'ready' }"
            @click="
              filters.status = 'ready';
              fetchDocuments();
            "
          >
            已完成
          </button>
          <button
            class="chip"
            :class="{ active: filters.status === 'processing' }"
            @click="
              filters.status = 'processing';
              fetchDocuments();
            "
          >
            处理中
          </button>
          <button
            class="chip"
            :class="{ active: filters.status === 'failed' }"
            @click="
              filters.status = 'failed';
              fetchDocuments();
            "
          >
            异常
          </button>
        </div>

        <select
          v-model="filters.file_type"
          class="input"
          @change="fetchDocuments"
          style="max-width: 140px;"
        >
          <option value="">全部格式</option>
          <option value="pdf">PDF</option>
          <option value="docx">Word</option>
          <option value="xlsx">Excel</option>
          <option value="txt">TXT</option>
        </select>

        <select
          v-model="filters.department"
          class="input"
          @change="fetchDocuments"
          style="max-width: 140px;"
        >
          <option value="">全部部门</option>
          <option value="HR">HR</option>
          <option value="Finance">财务</option>
          <option value="Engineering">研发</option>
          <option value="Sales">销售</option>
        </select>

        <select
          v-model="filters.sortBy"
          class="input"
          @change="fetchDocuments"
          style="max-width: 180px;"
        >
          <option value="latest">按最近上传</option>
          <option value="failed_first">异常优先</option>
          <option value="processing_first">处理中优先</option>
        </select>
      </div>

      <div class="bulk-actions" v-if="selectedDocIds.length > 0">
        <div class="selection-badge">已选择 {{ selectedDocIds.length }} 项</div>
        <button class="btn btn-secondary btn-sm" @click="bulkRetry">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <polyline points="1 4 1 10 7 10"></polyline>
            <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
          </svg>
          批量重试
        </button>
        <button class="btn btn-secondary btn-sm" @click="bulkCheckStatus">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path
              d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.92-10.44l-3.28 3.28"
            ></path>
          </svg>
          状态同步
        </button>
        <button
          class="btn btn-secondary btn-sm btn-danger-ghost"
          @click="bulkDelete"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <polyline points="3 6 5 6 21 6"></polyline>
            <path
              d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
            ></path>
          </svg>
          批量删除
        </button>
      </div>
    </div>

    <!-- 上传进度 -->
    <div
      v-if="Object.keys(docStore.uploadProgress).length"
      class="upload-progress-area"
    >
      <div
        v-for="(prog, docId) in docStore.uploadProgress"
        :key="docId"
        class="progress-item card animate-slide-in"
      >
        <div class="progress-info">
          <span>{{ prog.fileName || `${String(docId).slice(0, 8)}...` }}</span>
          <span class="badge" :class="statusBadgeClass(prog.status)">{{
            progressLabel(prog.status)
          }}</span>
        </div>
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: `${prog.percentage}%` }"
          ></div>
        </div>
      </div>
    </div>

    <!-- 文档列表 -->
    <div class="documents-table card">
      <table class="data-table">
        <thead>
          <tr>
            <th width="40">
              <input
                type="checkbox"
                :checked="isAllSelected"
                @change="toggleSelectAll"
              />
            </th>
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
          <tr v-if="loading">
            <td colspan="8" class="empty-table">加载中...</td>
          </tr>
          <tr v-else-if="filteredAndSortedDocuments.length === 0">
            <td colspan="8" class="empty-table">
              暂无文档，先上传一个文件开始处理。
            </td>
          </tr>
          <tr
            v-else
            v-for="doc in filteredAndSortedDocuments"
            :key="doc.id"
            class="doc-row"
            :class="{ 'row-selected': selectedDocIds.includes(doc.id) }"
          >
            <td>
              <input type="checkbox" :value="doc.id" v-model="selectedDocIds" />
            </td>
            <td class="doc-name">
              <span class="doc-icon">{{ fileIcon(doc.file_type) }}</span
              >{{ doc.title }}
            </td>
            <td>
              <span class="badge badge-primary">{{
                doc.file_type?.split("/").pop() || "-"
              }}</span>
            </td>
            <td>{{ doc.department || "-" }}</td>
            <td>
              <span class="badge" :class="statusBadgeClass(doc.status)">{{
                progressLabel(doc.status)
              }}</span>
            </td>
            <td>
              {{
                doc.percentage ??
                docStore.uploadProgress[doc.id]?.percentage ??
                0
              }}%
            </td>
            <td class="text-muted">{{ formatDate(doc.created_at) }}</td>
            <td class="table-actions">
              <button
                class="btn btn-ghost btn-sm"
                @click="openDetailsDrawer(doc)"
              >
                详情
              </button>
              <button
                class="btn btn-ghost btn-sm"
                :disabled="openingOriginalDocId === doc.id"
                @click="openOriginalDocument(doc)"
              >
                {{ openingOriginalDocId === doc.id ? "打开中..." : "查看原文" }}
              </button>
              <button
                v-if="
                  ['failed', 'partial_failed', 'retrying'].includes(doc.status)
                "
                class="btn btn-ghost btn-sm"
                @click="retryDoc(doc.id)"
              >
                重试
              </button>
              <button
                v-if="doc.status === 'ready'"
                class="btn btn-ghost btn-sm"
                @click="$router.push('/chat')"
              >
                问答测试
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分页控制 -->
      <div class="pagination-bar" v-if="total > 0">
        <span class="text-muted">共 {{ total }} 条</span>
        <div class="pagination-controls">
          <button
            class="btn btn-secondary btn-sm"
            :disabled="page <= 1"
            @click="changePage(page - 1)"
          >
            上一页
          </button>
          <span class="page-current">{{ page }}</span>
          <button
            class="btn btn-secondary btn-sm"
            :disabled="page * size >= total"
            @click="changePage(page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </div>

    <!-- 侧边抽屉：文档详情 -->
    <div
      class="side-drawer-overlay"
      v-if="selectedDocForDetails"
      @click="closeDetailsDrawer"
    ></div>
    <aside class="side-drawer" :class="{ open: !!selectedDocForDetails }">
      <div v-if="selectedDocForDetails" class="drawer-content">
        <div class="drawer-header">
          <h3>文档详情</h3>
          <button class="btn btn-ghost btn-sm" @click="closeDetailsDrawer">
            关闭
          </button>
        </div>

        <div class="drawer-body">
          <div class="detail-block">
            <h4>基本信息</h4>
            <div class="info-grid">
              <span>文档名称</span
              ><strong>{{ selectedDocForDetails.title }}</strong>
              <span>文档 ID</span
              ><strong>{{ selectedDocForDetails.id }}</strong> <span>部门</span
              ><strong>{{ selectedDocForDetails.department || "-" }}</strong>
              <span>上传时间</span
              ><strong>{{
                formatDate(selectedDocForDetails.created_at)
              }}</strong>
            </div>
          </div>

          <div class="detail-block">
            <h4>处理状态</h4>
            <div
              class="status-box"
              :class="
                statusBadgeClass(selectedDocStatus).replace('badge-', 'bg-')
              "
            >
              <strong>{{ progressLabel(selectedDocStatus) }}</strong>
              <div v-if="selectedDocError" class="structured-error-box">
                <div class="error-header">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                  <span>错误详情</span>
                </div>
                <div class="error-content">
                  <p>{{ formatErrorMessage(selectedDocError) }}</p>
                </div>
              </div>
            </div>

            <div v-if="batchFailures.length" class="structured-failures">
              <h5>批次失败详情</h5>
              <ul>
                <li v-for="(err, idx) in batchFailures" :key="idx">
                  {{ err }}
                </li>
              </ul>
            </div>
          </div>

          <div class="detail-block" v-if="selectedEvents.length">
            <h4>执行追踪 (Trace)</h4>
            <ul class="event-list">
              <li v-for="(event, index) in selectedEvents" :key="index">
                <strong>{{ progressLabel(event.status) }}</strong>
                <span>{{ event.detail || "-" }}</span>
                <span class="text-muted">{{
                  formatDate(event.updated_at)
                }}</span>
              </li>
            </ul>
          </div>
        </div>

        <div class="drawer-footer">
          <button
            class="btn btn-secondary"
            :disabled="openingOriginalDocId === selectedDocForDetails.id"
            @click="openOriginalDocument(selectedDocForDetails)"
          >
            {{ openingOriginalDocId === selectedDocForDetails.id ? "打开中..." : "查看原文" }}
          </button>
          <button
            v-if="selectedDocStatus === 'ready'"
            class="btn btn-primary"
            @click="$router.push('/search')"
          >
            去检索验证
          </button>
          <button
            v-if="['failed', 'partial_failed'].includes(selectedDocStatus)"
            class="btn btn-secondary"
            @click="retryDoc(selectedDocForDetails.id)"
          >
            重试处理
          </button>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import dayjs from "dayjs";
import { useRouter } from "vue-router";
import { documentsApi } from "@/api/documents";
import { useDocumentStore } from "@/stores/documents";

// Types
interface DocumentItem {
  id: string;
  title: string;
  file_name?: string;
  file_type: string;
  department?: string;
  status: string;
  percentage?: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

interface DocEvent {
  status: string;
  detail?: string;
  error?: string;
  updated_at: string;
}

const router = useRouter();
const docStore = useDocumentStore();

// State
const documents = ref<DocumentItem[]>([]);
const loading = ref(false);
const total = ref(0);
const page = ref(1);
const size = ref(20);

// Filters & Selection
const filters = ref({
  query: "",
  status: "",
  file_type: "",
  department: "",
  sortBy: "latest", // latest, failed_first, processing_first
});
const selectedDocIds = ref<string[]>([]);

// Drawer State
const selectedDocForDetails = ref<DocumentItem | null>(null);
const selectedEvents = ref<DocEvent[]>([]);
const selectedDocStatus = ref("unknown");
const selectedDocError = ref("");
const batchFailures = ref<string[]>([]);
const openingOriginalDocId = ref("");

// Computed
const readyCount = computed(
  () => documents.value.filter((d) => d.status === "ready").length,
);
const processingCount = computed(
  () =>
    documents.value.filter((d) =>
      [
        "queued",
        "uploaded",
        "parsing",
        "chunking",
        "indexing",
        "retrying",
      ].includes(d.status),
    ).length,
);
const failedCount = computed(
  () =>
    documents.value.filter((d) =>
      ["failed", "partial_failed"].includes(d.status),
    ).length,
);

const isAllSelected = computed(() => {
  if (filteredAndSortedDocuments.value.length === 0) return false;
  return (
    selectedDocIds.value.length === filteredAndSortedDocuments.value.length
  );
});

const filteredAndSortedDocuments = computed(() => {
  let docs = [...documents.value];

  if (filters.value.query) {
    const q = filters.value.query.toLowerCase();
    docs = docs.filter((d) => d.title?.toLowerCase().includes(q));
  }

  if (filters.value.file_type) {
    const ft = filters.value.file_type.toLowerCase();
    docs = docs.filter((d) => d.file_type?.toLowerCase().includes(ft));
  }

  if (filters.value.department) {
    docs = docs.filter((d) => d.department === filters.value.department);
  }

  // Frontend fallback sorting
  if (filters.value.sortBy === "failed_first") {
    docs.sort((a, b) => {
      const aFailed = ["failed", "partial_failed"].includes(a.status) ? 1 : 0;
      const bFailed = ["failed", "partial_failed"].includes(b.status) ? 1 : 0;
      return bFailed - aFailed;
    });
  } else if (filters.value.sortBy === "processing_first") {
    docs.sort((a, b) => {
      const aProc = [
        "queued",
        "uploaded",
        "parsing",
        "chunking",
        "indexing",
        "retrying",
      ].includes(a.status)
        ? 1
        : 0;
      const bProc = [
        "queued",
        "uploaded",
        "parsing",
        "chunking",
        "indexing",
        "retrying",
      ].includes(b.status)
        ? 1
        : 0;
      return bProc - aProc;
    });
  }

  return docs;
});

// Lifecycle
onMounted(() => {
  fetchDocuments();
});

// Methods
async function fetchDocuments() {
  loading.value = true;
  try {
    const params: Record<string, any> = { page: page.value, size: size.value };
    if (filters.value.status) {
      if (filters.value.status === "processing") params.status = "parsing";
      else params.status = filters.value.status;
    }
    if (filters.value.file_type) {
      params.file_type = filters.value.file_type;
    }
    if (filters.value.department) {
      params.department = filters.value.department;
    }

    const res = await documentsApi.list(params);
    documents.value = res.documents || res.items || [];
    total.value = res.total || documents.value.length;
    docStore.setDocuments(documents.value as any, total.value);
  } catch (err) {
    console.error("Failed to load documents", err);
    documents.value = [];
  } finally {
    loading.value = false;
  }
}

async function openOriginalDocument(doc: DocumentItem) {
  openingOriginalDocId.value = doc.id;
  try {
    const blob = await documentsApi.getOriginal(doc.id);
    const objectUrl = URL.createObjectURL(blob);
    const win = window.open(objectUrl, "_blank", "noopener,noreferrer");
    if (!win) {
      window.location.href = objectUrl;
    }
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  } catch (err) {
    console.error("Failed to open original document", err);
    alert("打开原文失败，请稍后重试。");
  } finally {
    openingOriginalDocId.value = "";
  }
}

function changePage(newPage: number) {
  page.value = newPage;
  fetchDocuments();
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedDocIds.value = [];
  } else {
    selectedDocIds.value = filteredAndSortedDocuments.value.map((d) => d.id);
  }
}

// Bulk Actions
async function bulkDelete() {
  if (!confirm(`确定要删除选中的 ${selectedDocIds.value.length} 个文档吗？`))
    return;
  const ids = [...selectedDocIds.value];
  selectedDocIds.value = [];
  for (const id of ids) {
    try {
      await documentsApi.delete(id);
      documents.value = documents.value.filter((d) => d.id !== id);
    } catch (e) {
      console.error(`Failed to delete ${id}`, e);
    }
  }
  fetchDocuments();
}

async function bulkRetry() {
  const ids = [...selectedDocIds.value];
  for (const id of ids) {
    await retryDoc(id);
  }
}

async function bulkCheckStatus() {
  const ids = [...selectedDocIds.value];
  for (const id of ids) {
    pollStatus(id, true);
  }
}

// Error Formatting
function formatErrorMessage(err: string): string {
  if (!err) return "";
  try {
    const parsed = JSON.parse(err);
    if (parsed.message) return parsed.message;
    if (parsed.detail) return typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail);
  } catch (e) {
    // not JSON
  }
  const lines = err.split('\n');
  if (lines.length > 3) {
    return lines[lines.length - 1] || lines[lines.length - 2] || err;
  }
  return err;
}

// Upload Logic
async function handleUpload(event: Event) {
  const target = event.target as HTMLInputElement;
  const files = Array.from(target.files || []);
  for (const file of files) {
    try {
      const res = await uploadFile(file);
      documents.value.unshift(res as any);
      docStore.updateUploadProgress((res as any).id, "queued", 0, file.name);
      pollStatus((res as any).id);
    } catch (error) {
      console.error("Upload failed:", error);
    }
  }
  target.value = "";
}

async function uploadFile(file: File) {
  const chunkThreshold = 8 * 1024 * 1024;
  const chunkSize = 2 * 1024 * 1024;

  if (file.size <= chunkThreshold) {
    return await documentsApi.upload(file);
  }

  const uploadKey = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const totalParts = Math.ceil(file.size / chunkSize);
  docStore.updateUploadProgress(uploadKey, "uploading", 0, file.name);

  const session = await documentsApi.createUploadSession({
    file_name: file.name,
    content_type: file.type || "application/octet-stream",
    file_size: file.size,
    total_parts: totalParts,
  } as any);

  for (let index = 0; index < totalParts; index += 1) {
    const start = index * chunkSize;
    const end = Math.min(file.size, start + chunkSize);
    const blob = file.slice(start, end);
    const partNumber = index + 1;
    await documentsApi.uploadChunk(
      (session as any).upload_id,
      partNumber,
      totalParts,
      blob,
    );
    const percentage = Math.min(
      95,
      Math.round((partNumber / totalParts) * 100),
    );
    docStore.updateUploadProgress(
      uploadKey,
      "uploading",
      percentage,
      file.name,
    );
  }

  const completed = await documentsApi.completeUpload(
    (session as any).upload_id,
  );
  docStore.clearUploadProgress(uploadKey);
  return completed;
}

// Status Polling
function pollStatus(docId: string, once = false) {
  const check = async () => {
    try {
      const status: any = await documentsApi.getStatus(docId);
      docStore.updateUploadProgress(
        docId,
        status.status,
        parseInt(status.percentage, 10) || 0,
      );
      const target = documents.value.find((d) => d.id === docId);
      if (target) {
        target.status = status.status;
        target.percentage = parseInt(status.percentage, 10) || 0;
        target.error_message = status.error_message;
      }

      if (selectedDocForDetails.value?.id === docId) {
        selectedDocStatus.value = status.status;
        selectedDocError.value = status.error_message || "";
      }

      if (["ready", "failed", "partial_failed"].includes(status.status)) {
        if (interval) clearInterval(interval);
        if (status.status === "ready") {
          setTimeout(() => docStore.clearUploadProgress(docId), 1500);
        }
      }
    } catch {
      if (interval) clearInterval(interval);
    }
  };

  let interval: any = null;
  if (once) {
    check();
  } else {
    interval = setInterval(check, 2000);
  }
}

async function retryDoc(docId: string) {
  await documentsApi.retry(docId);
  const target = documents.value.find((d) => d.id === docId);
  if (target) {
    target.status = "queued";
    target.percentage = 0;
  }
  pollStatus(docId);
}

// Drawer Details
async function openDetailsDrawer(doc: DocumentItem) {
  selectedDocForDetails.value = doc;
  selectedDocStatus.value = doc.status;
  selectedDocError.value = doc.error_message || "";
  selectedEvents.value = [];
  batchFailures.value = [];

  const [eventsRes, statusRes] = await Promise.all([
    documentsApi.getEvents(doc.id),
    documentsApi.getStatus(doc.id),
  ]);
  selectedEvents.value = (eventsRes as any).events || [];
  selectedDocStatus.value = (statusRes as any).status || "unknown";
  selectedDocError.value = (statusRes as any).error_message || "";
  batchFailures.value = extractBatchFailures(
    selectedEvents.value,
    selectedDocError.value,
  );
}

function closeDetailsDrawer() {
  selectedDocForDetails.value = null;
}

async function deleteDoc(docId: string) {
  if (!confirm("确定删除这个文档吗？")) return;
  try {
    await documentsApi.delete(docId);
    documents.value = documents.value.filter((d) => d.id !== docId);
  } catch (error) {
    console.error("Delete failed:", error);
  }
}

// Utils
function fileIcon(type: string) {
  if (!type) return "DOC";
  if (type.includes("pdf")) return "PDF";
  if (type.includes("word") || type.includes("docx")) return "DOC";
  if (type.includes("excel") || type.includes("xlsx")) return "XLS";
  if (type.includes("csv")) return "CSV";
  if (type.includes("image")) return "IMG";
  return "DOC";
}

function statusBadgeClass(status: string) {
  const map: Record<string, string> = {
    uploading: "badge-warning",
    ready: "badge-success",
    queued: "badge-warning",
    uploaded: "badge-warning",
    parsing: "badge-warning",
    chunking: "badge-warning",
    indexing: "badge-warning",
    retrying: "badge-warning",
    failed: "badge-danger",
    partial_failed: "badge-danger",
  };
  return map[status] || "badge-primary";
}

function progressLabel(status: string) {
  const labels: Record<string, string> = {
    uploading: "上传中",
    uploaded: "已上传",
    queued: "排队中",
    parsing: "解析中",
    chunking: "分块中",
    indexing: "建索引中",
    retrying: "重试中",
    ready: "已完成",
    failed: "失败",
    partial_failed: "部分失败",
    unknown: "未知",
  };
  return labels[status] || status || "未知";
}

function formatDate(date: string) {
  return date ? dayjs(date).format("YYYY-MM-DD HH:mm") : "-";
}

function extractBatchFailures(events: DocEvent[], errorMessage: string) {
  const content = [
    errorMessage,
    ...events.map((e) => e.error),
    ...events.map((e) => e.detail),
  ]
    .filter(Boolean)
    .join("；");
  const matches = content.match(/第\d+批失败[^；]*/g) || [];
  return [...new Set(matches)];
}
</script>

<style scoped>
.workbench-page {
  padding: 0 12px 12px;
  overflow-y: auto;
  height: 100%;
  position: relative;
  transition: padding-right var(--transition-base);
}

.workbench-page.drawer-open {
  padding-right: 420px; /* Make space for drawer */
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
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 140px;
  padding: 24px;
}

.stat-value {
  font-size: clamp(2.5rem, 4vw, 3rem);
  font-weight: 600;
  color: var(--color-primary);
  line-height: 1;
}

.stat-label {
  color: var(--text-secondary);
}

.filter-bar {
  max-width: 1240px;
  margin: 0 auto 16px;
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.filter-group {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.filter-chips {
  display: flex;
  background: var(--bg-surface-strong);
  padding: 4px;
  border-radius: 12px;
  gap: 2px;
}

.chip {
  padding: 6px 14px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.chip:hover {
  color: var(--text-primary);
}

.chip.active {
  background: var(--bg-surface);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
}



.bulk-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--bg-surface-strong);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  margin-bottom: 16px;
}

.selection-badge {
  font-size: 0.85rem;
  color: var(--text-primary);
  font-weight: 600;
  margin-right: 8px;
}

.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-surface);
  border-radius: 999px;
  font-size: 0.85rem;
}

.btn-danger-ghost {
  color: var(--color-danger);
  border-color: rgba(217, 45, 32, 0.3);
}

.btn-danger-ghost:hover {
  background: rgba(217, 45, 32, 0.05);
  border-color: var(--color-danger);
}

/* Custom Premium Checkbox */
input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  border: 1.5px solid var(--border-color-strong);
  border-radius: 4px;
  background-color: var(--bg-surface);
  cursor: pointer;
  position: relative;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  margin: 0;
  vertical-align: middle;
}

input[type="checkbox"]:hover {
  border-color: var(--color-primary);
}

input[type="checkbox"]:checked {
  background-color: var(--color-primary);
  border-color: var(--color-primary);
  transform: scale(1.05);
}

input[type="checkbox"]:checked::after {
  content: "";
  position: absolute;
  left: 5px;
  top: 1px;
  width: 5px;
  height: 10px;
  border: solid white;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

.upload-progress-area,
.documents-table {
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



.doc-row.row-selected {
  background-color: var(--bg-surface-hover);
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
  padding: 40px !important;
}

.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-top: 1px solid var(--border-color-subtle);
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-current {
  font-weight: 600;
  color: var(--text-primary);
}

/* Side Drawer Styles */
.side-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.2);
  z-index: 40;
  backdrop-filter: blur(2px);
}

.side-drawer {
  position: fixed;
  top: 0;
  right: -420px;
  width: 400px;
  height: 100vh;
  background: var(--bg-body);
  border-left: 1px solid var(--border-color);
  box-shadow: -10px 0 30px rgba(0, 0, 0, 0.1);
  z-index: 50;
  transition: right 300ms cubic-bezier(0.2, 0.8, 0.2, 1);
  display: flex;
  flex-direction: column;
}

.side-drawer.open {
  right: 0;
}

.drawer-content {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px;
  border-bottom: 1px solid var(--border-color-subtle);
}

.drawer-header h3 {
  font-size: 1.25rem;
  margin: 0;
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.detail-block h4 {
  font-size: 0.95rem;
  color: var(--text-secondary);
  margin-bottom: 16px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.info-grid {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 12px;
  font-size: 0.95rem;
}

.info-grid span {
  color: var(--text-tertiary);
}

.status-box {
  padding: 16px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.bg-danger {
  background: rgba(217, 45, 32, 0.08);
  border-color: rgba(217, 45, 32, 0.2);
}
.bg-success {
  background: rgba(18, 183, 106, 0.08);
  border-color: rgba(18, 183, 106, 0.2);
}
.bg-warning {
  background: rgba(247, 144, 9, 0.08);
  border-color: rgba(247, 144, 9, 0.2);
}

.error-text {
  margin-top: 8px;
  color: var(--color-danger);
  font-size: 0.9rem;
}

.structured-failures {
  margin-top: 16px;
  padding: 12px;
  background: var(--bg-surface-hover);
  border-radius: 8px;
}

.structured-failures h5 {
  margin-bottom: 8px;
  color: var(--text-secondary);
}

.event-list {
  display: grid;
  gap: 10px;
}

.event-list li {
  list-style: none;
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 8px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-color-subtle);
  font-size: 0.9rem;
}

.drawer-footer {
  padding: 24px;
  border-top: 1px solid var(--border-color-subtle);
  display: flex;
  gap: 12px;
  background: var(--bg-surface);
}

.drawer-footer .btn {
  flex: 1;
}

@media (max-width: 1000px) {
  .stats-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .workbench-page.drawer-open {
    padding-right: 12px; /* disable squash on mobile */
  }
  .side-drawer {
    width: 100%;
    right: -100%;
  }
  .stats-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .documents-table {
    overflow-x: auto;
  }
  .filter-group {
    flex-direction: column;
    width: 100%;
  }
  .filter-select {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .stats-row {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <div
    class="chat-composer-wrapper"
    :class="{ compact, 'drag-over': isDragOver }"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <div class="drop-overlay" v-if="isDragOver">
      <span class="drop-label">释放以上传文件</span>
    </div>
    <div class="chat-composer">
      <!-- Attached files list -->
      <div v-if="attachedFiles.length" class="attached-files">
        <div v-for="file in attachedFiles" :key="file.id" class="file-chip">
          <span class="file-icon">{{ getFileIcon(file.name) }}</span>
          <div class="file-info">
            <span class="file-name" :title="file.name">{{ file.name }}</span>
            <span class="file-status" :class="file.status">{{ getStatusLabel(file) }}</span>
          </div>
          <!-- Progress bar for uploading/processing -->
          <div v-if="['uploading', 'parsing', 'chunking', 'indexing'].includes(file.status)" class="chip-progress-bar">
            <div class="chip-progress-fill" :style="{ width: `${file.progress}%` }"></div>
          </div>
          <!-- Remove button -->
          <button class="remove-file-btn" type="button" @click="removeAttachedFile(file.id)" title="移除文档">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      </div>

      <textarea
        ref="textareaRef"
        :value="modelValue"
        class="hero-input"
        :placeholder="placeholder"
        rows="1"
        :disabled="disabled"
        @input="handleInput"
        @keydown.enter.exact.prevent="$emit('submit')"
      ></textarea>

      <div class="composer-bottom">
        <div class="composer-tools">
          <label class="tool-btn" title="添加文档进行问答" style="cursor: pointer;">
            <input
              type="file"
              style="display: none;"
              multiple
              @change="handleFileChange"
            />
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </label>
          <label class="model-selector">
            <span class="sr-only">{{ modelSelectorLabel }}</span>
            <select
              :value="selectedModel"
              class="model-select"
              @change="$emit('update:selectedModel', ($event.target as HTMLSelectElement).value)"
            >
              <option value="qwen2.5:1.5b">DocMind Smart 1.0 (1.5B)</option>
              <option value="qwen2.5:7b">DocMind Smart 1.0 (7B)</option>
            </select>
          </label>
        </div>
        <div class="composer-actions">
          <button
            class="send-btn"
            type="button"
            :disabled="disabled || !modelValue.trim()"
            title="发送消息"
            @click="$emit('submit')"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="19" x2="12" y2="5"></line>
              <polyline points="5 12 12 5 19 12"></polyline>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue"
import { storeToRefs } from "pinia"
import { useChatStore, type AttachedFile } from "@/stores/chat"
import { documentsApi } from "@/api/documents"

const focusLabel = "聚焦输入框"
const modelSelectorLabel = "选择模型"

const props = defineProps<{
  modelValue: string
  selectedModel: string
  placeholder: string
  disabled?: boolean
  compact?: boolean
}>()

const emit = defineEmits<{
  "update:modelValue": [value: string]
  "update:selectedModel": [value: string]
  submit: []
}>()

const chatStore = useChatStore()
const { attachedFiles } = storeToRefs(chatStore)

const textareaRef = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.modelValue,
  async () => {
    await nextTick()
    resizeTextarea()
  },
  { immediate: true }
)

onMounted(() => {
  setTimeout(() => textareaRef.value?.focus(), 100)
})

function focusInput() {
  textareaRef.value?.focus()
}

defineExpose({ focusInput })

function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  emit("update:modelValue", target.value)
  resizeTextarea()
}

function resizeTextarea() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = "auto"
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

const isDragOver = ref(false)
let dragCounter = 0

function onDragEnter() {
  dragCounter++
  isDragOver.value = true
}

function onDragOver() {
  isDragOver.value = true
}

function onDragLeave() {
  dragCounter--
  if (dragCounter <= 0) {
    dragCounter = 0
    isDragOver.value = false
  }
}

function onDrop(e: DragEvent) {
  dragCounter = 0
  isDragOver.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  for (const file of files) {
    const fileId = `file-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const newFile: AttachedFile = {
      id: fileId,
      name: file.name,
      status: 'uploading',
      progress: 0,
    }
    attachedFiles.value.push(newFile)
    void uploadAttachedFile(file, fileId)
  }
}


async function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  for (const file of files) {
    const fileId = `file-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const newFile: AttachedFile = {
      id: fileId,
      name: file.name,
      status: 'uploading',
      progress: 0,
    }
    attachedFiles.value.push(newFile)
    
    // Trigger upload in background
    void uploadAttachedFile(file, fileId)
  }
  target.value = ""
}

async function uploadAttachedFile(file: File, fileId: string) {
  const chunkThreshold = 8 * 1024 * 1024
  const chunkSize = 2 * 1024 * 1024

  try {
    let res: any
    if (file.size <= chunkThreshold) {
      res = await documentsApi.upload(file)
    } else {
      const totalParts = Math.ceil(file.size / chunkSize)
      const session: any = await documentsApi.createUploadSession({
        file_name: file.name,
        content_type: file.type || "application/octet-stream",
        file_size: file.size,
        total_parts: totalParts,
      } as any)

      for (let index = 0; index < totalParts; index += 1) {
        // Double check if file was deleted during upload
        if (!attachedFiles.value.some(f => f.id === fileId)) return

        const start = index * chunkSize
        const end = Math.min(file.size, start + chunkSize)
        const blob = file.slice(start, end)
        const partNumber = index + 1
        await documentsApi.uploadChunk(session.upload_id, partNumber, totalParts, blob)
        const percentage = Math.min(95, Math.round((partNumber / totalParts) * 100))
        
        const f = attachedFiles.value.find(x => x.id === fileId)
        if (f) {
          f.progress = percentage
        }
      }
      res = await documentsApi.completeUpload(session.upload_id)
    }

    const docId = res.id || res.document?.id
    const f = attachedFiles.value.find(x => x.id === fileId)
    if (f) {
      f.status = 'queued'
      f.progress = 100
      f.docId = docId
      if (docId) {
        pollAttachedFileStatus(fileId, docId)
      }
    }
  } catch (error) {
    console.error("Upload failed in chat composer:", error)
    const f = attachedFiles.value.find(x => x.id === fileId)
    if (f) {
      f.status = 'failed'
    }
  }
}

function pollAttachedFileStatus(fileId: string, docId: string) {
  const check = async () => {
    if (!attachedFiles.value.some(f => f.id === fileId)) {
      if (interval) clearInterval(interval)
      return
    }

    try {
      const status: any = await documentsApi.getStatus(docId)
      const f = attachedFiles.value.find(x => x.id === fileId)
      if (f) {
        f.status = status.status
        f.progress = parseInt(status.percentage, 10) || 0
      }

      if (['ready', 'failed', 'partial_failed'].includes(status.status)) {
        if (interval) clearInterval(interval)
      }
    } catch {
      if (interval) clearInterval(interval)
    }
  }

  const interval = setInterval(check, 2000)
}

async function removeAttachedFile(fileId: string) {
  const fileRef = attachedFiles.value.find(f => f.id === fileId)
  attachedFiles.value = attachedFiles.value.filter(f => f.id !== fileId)
  if (fileRef?.docId) {
    try {
      await documentsApi.delete(fileRef.docId)
    } catch (err) {
      console.error("Failed to delete document from backend:", err)
    }
  }
}

function getFileIcon(fileName: string) {
  const ext = fileName.split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return 'PDF'
  if (['doc', 'docx'].includes(ext)) return 'DOC'
  if (['xls', 'xlsx'].includes(ext)) return 'XLS'
  if (['ppt', 'pptx'].includes(ext)) return 'PPT'
  if (ext === 'csv') return 'CSV'
  if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) return 'IMG'
  return 'TXT'
}

function getStatusLabel(file: AttachedFile) {
  if (file.status === 'uploading') return `上传中 ${file.progress}%`
  if (file.status === 'queued') return '排队中'
  if (file.status === 'parsing') return '解析中'
  if (file.status === 'chunking') return '分块中'
  if (file.status === 'indexing') return '建索引中'
  if (file.status === 'ready') return '已就绪'
  if (['failed', 'partial_failed'].includes(file.status)) return '失败'
  return '处理中'
}
</script>

<style scoped>
.chat-composer-wrapper {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  position: relative;
}

.chat-composer-wrapper.drag-over .chat-composer {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(217, 119, 87, 0.2);
}

.drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: grid;
  place-items: center;
  border-radius: var(--radius-lg);
  background: rgba(217, 119, 87, 0.08);
  border: 2px dashed var(--color-primary);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  pointer-events: none;
}

.drop-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-primary);
}

.chat-composer {
  width: 100%;
  background: var(--bg-sidebar);
  border: 1px solid var(--border-color-strong);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
  padding: 16px 20px;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  transition: box-shadow var(--transition-base), border-color var(--transition-base);
}

.chat-composer:focus-within {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-lg), 0 0 0 3px var(--color-primary-soft);
}

.hero-input {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  min-height: 48px;
  background: transparent;
  color: var(--text-primary);
  font-size: 1.05rem;
  line-height: 1.5;
  padding: 0;
}

.hero-input::placeholder {
  color: var(--text-tertiary);
}

.composer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}

.composer-tools,
.composer-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tool-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  background: var(--bg-surface-strong);
  display: grid;
  place-items: center;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.tool-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  transform: scale(1.05);
}

.model-selector {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border-color);
  background: var(--bg-surface-strong);
  border-radius: var(--radius-full);
  padding: 2px 10px 2px 10px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.model-selector:hover {
  border-color: var(--border-color-strong);
  background: var(--bg-surface-hover);
}

.model-select {
  border: 0;
  background: transparent;
  padding: 4px 18px 4px 4px;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  appearance: none;
  font-weight: 500;
  outline: none;
  transition: color var(--transition-fast);
  background-image: url('data:image/svg+xml;utf8,<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="%239c9a94" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>');
  background-repeat: no-repeat;
  background-position: right center;
}

.model-selector:hover .model-select {
  color: var(--text-primary);
}

.send-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 0;
  background: var(--color-primary);
  color: var(--text-on-primary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: 0 4px 12px rgba(217, 119, 87, 0.16);
}

.send-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
  transform: scale(1.05);
  box-shadow: 0 6px 16px rgba(217, 119, 87, 0.28);
}

.send-btn:active:not(:disabled) {
  transform: scale(0.95);
}

.send-btn:disabled {
  background: var(--bg-surface-strong);
  color: var(--text-tertiary);
  cursor: not-allowed;
  box-shadow: none;
}

/* Attached Files Styling */
.attached-files {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  width: 100%;
}

.file-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 8px 12px;
  min-width: 150px;
  max-width: 240px;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  animation: slideIn var(--transition-fast);
}

.theme-dark .file-chip {
  background: rgba(25, 25, 25, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
}

.theme-light .file-chip {
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(0, 0, 0, 0.06);
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.03);
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.file-chip .file-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--bg-input);
  display: grid;
  place-items: center;
  font-size: 10px;
  font-weight: 700;
  color: var(--color-primary);
  border: 1px solid var(--border-color);
  flex-shrink: 0;
}

.file-chip .file-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.file-chip .file-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-chip .file-status {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-top: 1px;
}

.file-chip .file-status.ready {
  color: var(--color-success);
  font-weight: 500;
}

.file-chip .file-status.failed {
  color: var(--color-danger);
}

.chip-progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: transparent;
}

.chip-progress-fill {
  height: 100%;
  background: var(--color-primary);
  transition: width 0.2s ease-out;
}

.remove-file-btn {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 0;
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.theme-dark .remove-file-btn {
  background: rgba(255, 255, 255, 0.08);
}

.remove-file-btn:hover {
  background: var(--color-danger);
  color: var(--text-on-primary);
  transform: scale(1.1);
}
</style>

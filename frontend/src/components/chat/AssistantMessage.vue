<template>
  <div class="assistant-row">
    <div class="assistant-shell" :data-layout="documentLayout ? 'document' : 'bubble'">
      <div class="assistant-head">
        <div class="assistant-badge">DocMind</div>
        <span class="assistant-subtitle">
          {{ isStreaming ? "正在基于检索证据生成回答" : "基于当前知识库与检索结果生成" }}
        </span>
      </div>

      <details v-if="message.citations?.length" class="thought-process">
        <summary>显示思路</summary>
        <div class="thought-content">
          <div class="thought-title">引用依据</div>
          <div
            v-for="(cite, index) in message.citations"
            :key="`${cite.doc_id}-${cite.page_number}-${index}`"
            class="thought-cite-item"
          >
            《{{ cite.doc_title || "未命名文档" }}》 / {{ cite.section_title || "未命名章节" }} | 页码：{{ cite.page_number ?? "-" }}
          </div>
        </div>
      </details>

      <div v-if="message.content" class="assistant-body">
        <div class="assistant-copy markdown-body" v-html="rendered"></div>
        <span v-if="isStreaming" class="streaming-cursor" aria-hidden="true"></span>
      </div>

      <div class="assistant-actions">
        <button class="action-button" title="复制" @click="$emit('copy', message.content)">复制</button>
        <button class="action-button" title="有帮助" @click="$emit('feedback', message.id, 1)">有帮助</button>
        <button class="action-button" title="待改进" @click="$emit('feedback', message.id, -1)">待改进</button>
        <button class="action-button" title="重试" @click="$emit('retry')">重试</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { marked } from "marked"
import type { ChatMessage } from "@/stores/chat"

const props = defineProps<{
  message: ChatMessage
  isStreaming?: boolean
}>()

defineEmits<{
  copy: [content: string]
  feedback: [messageId: string, rating: number]
  retry: []
}>()

const rendered = computed(() => marked.parse(props.message.content || "", { breaks: true }) as string)

const documentLayout = computed(() => {
  const content = (props.message.content || "").trim()
  if (!content) return false
  if (/```/.test(content)) return true
  if (/^\s{0,3}(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|\|.+\|)/m.test(content)) return true
  const paragraphs = content
    .split(/\n\s*\n/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
  return paragraphs.length >= 2 || content.split("\n").filter((line) => line.trim()).length >= 8
})
</script>

<style scoped>
.assistant-row {
  display: flex;
  justify-content: flex-start;
}

.assistant-shell {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
}

.assistant-shell[data-layout="document"] {
  width: 100%;
}

.assistant-head,
.assistant-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.assistant-badge {
  padding: 7px 12px;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary-hover);
  font-size: 12px;
  font-weight: 700;
}

.assistant-subtitle {
  color: var(--text-secondary);
  font-size: 13px;
}

.assistant-copy {
  font-size: 1rem;
  line-height: 1.78;
  color: var(--text-primary);
}

.assistant-body {
  position: relative;
}

.thought-process {
  border-left: 2px solid var(--border-color);
  padding-left: 16px;
  margin: 4px 0 12px 4px;
}

.thought-process summary {
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  user-select: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.thought-process summary:hover {
  color: var(--text-primary);
}

.thought-content {
  margin-top: 12px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.thought-title {
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.thought-cite-item {
  margin-bottom: 6px;
  padding-left: 12px;
  position: relative;
}

.thought-cite-item::before {
  content: "•";
  position: absolute;
  left: 0;
  color: var(--text-tertiary);
}

.assistant-actions {
  flex-wrap: wrap;
}

.action-button {
  border: 0;
  padding: 8px 12px;
  border-radius: 999px;
  color: var(--text-secondary);
  background: transparent;
  transition: transform var(--transition-fast), background-color var(--transition-fast);
}

.action-button:hover {
  transform: translateY(-1px);
  background: var(--bg-surface-hover);
}

.streaming-cursor {
  display: inline-block;
  width: 2px;
  height: 1.05em;
  margin-left: 4px;
  vertical-align: text-bottom;
  background: var(--color-primary);
  animation: assistant-cursor-blink 1s step-end infinite;
}

@keyframes assistant-cursor-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

:deep(.markdown-body p) {
  margin: 0;
}

:deep(.markdown-body p + p) {
  margin-top: 12px;
}

:deep(.markdown-body ul),
:deep(.markdown-body ol) {
  margin: 10px 0 0;
  padding-left: 20px;
}

:deep(.markdown-body code) {
  font-family: var(--font-mono);
  padding: 2px 6px;
  border-radius: 8px;
  background: var(--bg-code);
}

:deep(.markdown-body pre) {
  overflow-x: auto;
  padding: 14px 16px;
  border-radius: 18px;
  background: var(--bg-code);
}

:deep(.markdown-body table) {
  width: 100%;
  border-collapse: collapse;
  margin-top: 12px;
  font-size: 14px;
}

:deep(.markdown-body th),
:deep(.markdown-body td) {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color-subtle);
  text-align: left;
}
</style>

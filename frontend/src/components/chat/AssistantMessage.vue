<template>
  <div class="assistant-row">
    <div class="assistant-shell" :data-layout="documentLayout ? 'document' : 'bubble'">
      <div class="assistant-head">
        <div class="assistant-badge">DocMind</div>
        <span class="assistant-subtitle">
          {{ isStreaming ? streamingSubtitle : readySubtitle }}
        </span>
      </div>

      <div v-if="structured.title || structured.conclusion || structured.sections.length || structured.compareTable" class="answer-outline">
        <div v-if="structured.title" class="outline-title">{{ structured.title }}</div>
        <div v-if="structured.conclusion" class="outline-conclusion">
          <span class="outline-label">{{ conclusionLabel }}</span>
          <p>{{ structured.conclusion }}</p>
        </div>
        <div v-if="structured.compareTable" class="outline-block">
          <div class="outline-label">{{ compareLabel }}</div>
          <div class="markdown-body" v-html="renderMarkdown(structured.compareTable)"></div>
        </div>
        <div v-for="section in structured.sections" :key="section.title" class="outline-block">
          <div class="outline-label">{{ section.title }}</div>
          <div class="markdown-body" v-html="renderMarkdown(section.body)"></div>
        </div>
      </div>

      <section v-if="citationGroups.length" class="evidence-board">
        <div class="evidence-head">
          <strong>{{ evidenceTitle }}</strong>
          <span>{{ citationSummary }}</span>
        </div>
        <div class="evidence-groups">
          <article v-for="group in citationGroups" :key="group.key" class="evidence-card">
            <header class="evidence-card-head">
              <div>
                <div class="evidence-doc-title">{{ group.docTitle }}</div>
                <div class="evidence-doc-meta">{{ group.sectionSummary }}</div>
              </div>
              <span class="evidence-count">{{ group.items.length }} {{ evidenceCountUnit }}</span>
            </header>
            <ul class="evidence-list">
              <li v-for="item in group.items" :key="item.key" class="evidence-item">
                <div class="evidence-item-meta">
                  <span>{{ item.sectionTitle }}</span>
                  <span>{{ pageLabel }} {{ item.pageNumber }}</span>
                </div>
                <p>{{ item.snippet }}</p>
              </li>
            </ul>
          </article>
        </div>
      </section>

      <div v-if="structured.remainder" class="assistant-body">
        <div class="assistant-copy markdown-body" v-html="rendered"></div>
        <span v-if="isStreaming" class="streaming-cursor" aria-hidden="true"></span>
      </div>

      <div class="assistant-actions">
        <button class="action-button" :title="copyLabel" @click="$emit('copy', message.content)">{{ copyLabel }}</button>
        <button class="action-button" :title="helpfulLabel" @click="$emit('feedback', message.id, 1)">{{ helpfulLabel }}</button>
        <button class="action-button" :title="improveLabel" @click="$emit('feedback', message.id, -1)">{{ improveLabel }}</button>
        <button class="action-button" :title="retryLabel" @click="$emit('retry')">{{ retryLabel }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { marked } from "marked"
import type { ChatMessage } from "@/stores/chat"

type StructuredSection = {
  title: string
  body: string
}

type StructuredAnswer = {
  title: string
  conclusion: string
  compareTable: string
  sections: StructuredSection[]
  remainder: string
}

type CitationViewItem = {
  key: string
  sectionTitle: string
  pageNumber: string
  snippet: string
}

type CitationGroup = {
  key: string
  docTitle: string
  sectionSummary: string
  items: CitationViewItem[]
}

const streamingSubtitle = "\u6b63\u5728\u57fa\u4e8e\u68c0\u7d22\u8bc1\u636e\u751f\u6210\u56de\u7b54"
const readySubtitle = "\u57fa\u4e8e\u5f53\u524d\u77e5\u8bc6\u5e93\u4e0e\u68c0\u7d22\u7ed3\u679c\u751f\u6210"
const conclusionLabel = "\u7ed3\u8bba"
const compareLabel = "\u7ed3\u6784\u5316\u5bf9\u6bd4"
const evidenceTitle = "\u5f15\u7528\u4f9d\u636e"
const pageLabel = "\u9875\u7801"
const evidenceCountUnit = "\u6761"
const copyLabel = "\u590d\u5236"
const helpfulLabel = "\u6709\u5e2e\u52a9"
const improveLabel = "\u5f85\u6539\u8fdb"
const retryLabel = "\u91cd\u8bd5"

const props = defineProps<{
  message: ChatMessage
  isStreaming?: boolean
}>()

defineEmits<{
  copy: [content: string]
  feedback: [messageId: string, rating: number]
  retry: []
}>()

const structured = computed(() => parseStructuredAnswer(props.message.content || ""))
const rendered = computed(() => renderMarkdown(structured.value.remainder))

const citationGroups = computed<CitationGroup[]>(() => {
  const groups = new Map<string, CitationGroup>()
  for (const cite of props.message.citations || []) {
    const docTitle = (cite.doc_title || "\u672a\u547d\u540d\u6587\u6863").trim()
    const sectionTitle = (cite.section_title || "\u672a\u547d\u540d\u7ae0\u8282").trim()
    const pageNumber = String(cite.page_number ?? "-")
    const snippet = String(cite.snippet || "").trim() || "\u672a\u63d0\u4f9b\u7247\u6bb5\u9884\u89c8"
    const key = `${cite.doc_id || docTitle}:${docTitle}`
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        docTitle,
        sectionSummary: "",
        items: [],
      })
    }
    const group = groups.get(key)!
    group.items.push({
      key: `${key}:${sectionTitle}:${pageNumber}:${snippet.slice(0, 20)}`,
      sectionTitle,
      pageNumber,
      snippet,
    })
  }

  return Array.from(groups.values()).map((group) => {
    const uniqueSections = Array.from(new Set(group.items.map((item) => item.sectionTitle)))
    return {
      ...group,
      sectionSummary:
        uniqueSections.length > 1
          ? uniqueSections.slice(0, 3).join("\u3001")
          : uniqueSections[0] || "\u672a\u547d\u540d\u7ae0\u8282",
    }
  })
})

const citationSummary = computed(() => {
  const docCount = citationGroups.value.length
  const snippetCount = citationGroups.value.reduce((sum, group) => sum + group.items.length, 0)
  return `\u5171 ${docCount} \u4efd\u6587\u6863\uff0c${snippetCount} \u6761\u8bc1\u636e`
})

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

function renderMarkdown(content: string) {
  return marked.parse(content || "", { breaks: true }) as string
}

function parseStructuredAnswer(content: string): StructuredAnswer {
  const normalized = content.trim()
  if (!normalized) {
    return { title: "", conclusion: "", compareTable: "", sections: [], remainder: "" }
  }

  let working = normalized
  const titleMatch = working.match(/^##\s+([^\n]+)\n?/m)
  const title = titleMatch?.[1]?.trim() || ""
  if (titleMatch) {
    working = working.replace(titleMatch[0], "").trim()
  }

  const conclusionMatch = working.match(/\*\*(?:直接结论|结论|摘要结论|对比结论)[:：]?\*\*\s*([^\n]+)/)
  const conclusion = conclusionMatch?.[1]?.trim() || ""
  if (conclusionMatch) {
    working = working.replace(conclusionMatch[0], "").trim()
  }

  let compareTable = ""
  const tableMatch = working.match(/((?:^\|.+\|\s*$\n?){2,})/m)
  if (tableMatch) {
    compareTable = tableMatch[1].trim()
    working = working.replace(tableMatch[1], "").trim()
  }

  const recognizedTitles = new Set([
    "\u6458\u8981\u8303\u56f4",
    "\u5173\u952e\u8981\u70b9",
    "\u5f85\u786e\u8ba4\u4e8b\u9879",
    "\u5efa\u8bae\u8ffd\u95ee",
    "\u76f8\u5173\u4f9d\u636e",
    "\u4f7f\u7528\u5efa\u8bae",
    "\u5f15\u7528\u4f9d\u636e",
    "\u5f85\u8865\u5145\u4fe1\u606f",
  ])

  const sections: StructuredSection[] = []
  const headingMatches = [...working.matchAll(/^###\s+([^\n]+)$/gm)]
  if (headingMatches.length) {
    let rebuiltRemainder = working
    for (let index = 0; index < headingMatches.length; index += 1) {
      const match = headingMatches[index]
      const sectionTitle = match[1].trim()
      const start = match.index ?? 0
      const end = index + 1 < headingMatches.length ? (headingMatches[index + 1].index ?? working.length) : working.length
      if (!recognizedTitles.has(sectionTitle)) {
        continue
      }
      const block = working.slice(start, end).trim()
      const body = block.replace(match[0], "").trim()
      if (!body) {
        continue
      }
      sections.push({ title: sectionTitle, body })
      rebuiltRemainder = rebuiltRemainder.replace(block, "").trim()
    }
    working = rebuiltRemainder
  }

  working = working.replace(/^---$/gm, "").trim()

  return {
    title,
    conclusion,
    compareTable,
    sections,
    remainder: working,
  }
}
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
.assistant-actions,
.evidence-head,
.evidence-card-head {
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

.answer-outline,
.evidence-board {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--bg-surface);
}

.outline-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.outline-conclusion,
.outline-block {
  display: grid;
  gap: 8px;
}

.outline-conclusion p {
  margin: 0;
  color: var(--text-primary);
  line-height: 1.7;
}

.outline-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.evidence-head {
  justify-content: space-between;
  flex-wrap: wrap;
}

.evidence-head strong {
  color: var(--text-primary);
  font-size: 14px;
}

.evidence-head span,
.evidence-doc-meta,
.evidence-count,
.evidence-item-meta {
  color: var(--text-secondary);
  font-size: 12px;
}

.evidence-groups {
  display: grid;
  gap: 10px;
}

.evidence-card {
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--border-color-subtle);
  background: var(--bg-app);
}

.evidence-card-head {
  justify-content: space-between;
  align-items: flex-start;
}

.evidence-doc-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.evidence-list {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.evidence-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--bg-surface);
}

.evidence-item-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.evidence-item p {
  margin: 0;
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
}

.assistant-copy {
  font-size: 1rem;
  line-height: 1.78;
  color: var(--text-primary);
}

.assistant-body {
  position: relative;
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

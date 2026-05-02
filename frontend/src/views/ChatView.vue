<template>
  <div class="chat-page">
    <section v-if="showHistoryList" class="history-state card-shell">
      <div class="history-header">
        <div>
          <p class="section-kicker">历史会话</p>
          <h2>继续上一次工作</h2>
          <p class="section-copy">你可以快速回到之前的问答、引用和检索结果。</p>
        </div>
        <button class="btn btn-primary btn-lg" @click="startFreshChat">新建对话</button>
      </div>

      <div class="history-toolbar">
        <label class="history-search">
          <span>⌕</span>
          <input v-model="sessionSearch" class="input history-search-input" placeholder="搜索会话标题" />
        </label>
        <span class="history-summary">共 {{ filteredSessions.length }} 个会话</span>
      </div>

      <div class="history-list">
        <button
          v-for="session in filteredSessions"
          :key="session.id"
          class="history-item"
          @click="openSession(session.id)"
        >
          <div>
            <strong>{{ session.title }}</strong>
            <span>{{ formatRelativeTime(session.updatedAt) }}</span>
          </div>
          <small>打开</small>
        </button>
        <div v-if="filteredSessions.length === 0" class="empty-panel">
          <p>没有匹配的会话记录。</p>
          <span>可以直接新建一轮问答，或更换关键词继续检索。</span>
        </div>
      </div>
    </section>

    <section v-else-if="showHeroState" class="hero-state">
      <div class="hero-intro">
        <p class="section-kicker">企业文档工作台</p>
        <h2>让检索、引用和回答落在同一条链路上</h2>
        <p class="section-copy">上传制度、预算、采购、审批等文档后，DocMind 会优先基于证据回答，并给出可追溯引用。</p>
      </div>

      <div class="hero-composer card-shell">
        <textarea
          ref="inputRef"
          v-model="inputMessage"
          class="hero-input"
          placeholder="请输入问题，例如：总结差旅报销制度的审批链路，并标注引用位置"
          rows="1"
          :disabled="chatStore.isStreaming"
          @keydown.enter.exact.prevent="handleSend"
          @input="autoResize"
        ></textarea>

        <div class="composer-bottom">
          <div class="composer-tools">
            <button class="composer-plus" @click="focusInput">+</button>
            <label class="model-selector">
              <span class="sr-only">选择模型</span>
              <select v-model="selectedModel" class="model-select">
                <option value="docmind-smart">标准问答</option>
                <option value="docmind-retrieval">检索增强</option>
                <option value="docmind-brief">精简速答</option>
              </select>
            </label>
          </div>
          <button class="btn btn-primary" :disabled="chatStore.isStreaming || !inputMessage.trim()" @click="handleSend">发送</button>
        </div>
      </div>

      <div class="quick-grid">
        <button v-for="prompt in quickPrompts" :key="prompt.label" class="quick-card" @click="sendQuickPrompt(prompt.text)">
          <strong>{{ prompt.label }}</strong>
          <span>{{ prompt.hint }}</span>
        </button>
      </div>

      <div class="onboarding card-shell">
        <div class="onboarding-header">
          <strong>建议从这几步开始</strong>
          <span>帮助你快速验证链路是否完整</span>
        </div>
        <button v-for="item in onboardingItems" :key="item" class="onboarding-item" @click="sendQuickPrompt(item)">
          <span class="onboarding-dot"></span>
          <span>{{ item }}</span>
        </button>
      </div>
    </section>

    <section v-else class="conversation-state">
      <div class="conversation-stream card-shell" ref="messagesRef">
        <div v-for="msg in chatStore.messages" :key="msg.id" class="message-row" :class="msg.role === 'user' ? 'user-row' : 'assistant-row'">
          <div v-if="msg.role === 'user'" class="message-bubble user-bubble">
            <p>{{ msg.content }}</p>
          </div>

          <template v-else>
            <div class="assistant-head">
              <div class="assistant-badge">DocMind</div>
              <span class="assistant-subtitle">基于当前知识库与检索结果生成</span>
            </div>
            <div v-if="msg.content" class="assistant-copy markdown-body" v-html="renderMarkdown(msg.content)"></div>

            <div v-if="msg.citations?.length" class="citation-row">
              <span v-for="cite in msg.citations" :key="`${cite.doc_id}-${cite.page_number}-${cite.section_title}`" class="citation-pill">
                {{ cite.doc_title }} / P{{ cite.page_number ?? '-' }}
              </span>
            </div>

            <div class="assistant-actions">
              <button class="action-button" title="复制" @click="copyMessage(msg.content)">复制</button>
              <button class="action-button" title="有帮助" @click="submitFeedback(msg.id, 1)">有帮助</button>
              <button class="action-button" title="待改进" @click="submitFeedback(msg.id, -1)">待改进</button>
              <button class="action-button" title="重试" @click="retryLastPrompt">重试</button>
            </div>
          </template>
        </div>

        <div v-if="chatStore.isStreaming && chatStore.streamStatus !== 'streaming'" class="status-line">
          <span class="status-chip">{{ chatStore.streamStatusMsg || '正在准备回答，请稍候…' }}</span>
        </div>
      </div>

      <div class="floating-composer">
        <div class="hero-composer compact card-shell">
          <textarea
            ref="replyInputRef"
            v-model="inputMessage"
            class="hero-input"
            placeholder="继续追问、补充条件或要求引用更精确的段落"
            rows="1"
            :disabled="chatStore.isStreaming"
            @keydown.enter.exact.prevent="handleSend"
            @input="autoResizeReply"
          ></textarea>

          <div class="composer-bottom">
            <div class="composer-tools">
              <button class="composer-plus" @click="focusReplyInput">+</button>
              <label class="model-selector">
                <span class="sr-only">选择模型</span>
                <select v-model="selectedModel" class="model-select">
                  <option value="docmind-smart">标准问答</option>
                  <option value="docmind-retrieval">检索增强</option>
                  <option value="docmind-brief">精简速答</option>
                </select>
              </label>
            </div>
            <button class="btn btn-primary" :disabled="chatStore.isStreaming || !inputMessage.trim()" @click="handleSend">发送</button>
          </div>
        </div>

        <p class="footer-note">回答会优先附带引用。若证据不足，系统会明确提示置信度和原因。</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { marked } from 'marked'
import { useChatStore } from '@/stores/chat'
import { useSSE } from '@/composables/useSSE'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { chatApi } from '@/api/chat'

const chatStore = useChatStore()
const { sendMessage } = useSSE()
const messagesRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)
const replyInputRef = ref<HTMLTextAreaElement | null>(null)
const inputMessage = ref('')
const sessionSearch = ref('')
const selectedModel = ref('docmind-smart')
const { scrollToBottom } = useAutoScroll(messagesRef)

const quickPrompts = [
  { label: '制度问答', hint: '围绕制度、流程、职责追问', text: '请总结当前差旅制度的审批链路，并说明各角色职责。' },
  { label: '检索验证', hint: '检查上传与召回链路是否正常', text: '请说明文档上传后是如何进入检索链路的。' },
  { label: '写作辅助', hint: '生成汇报、说明与总结', text: '请起草一份平台实施进展说明，包含风险与下一步计划。' },
  { label: '运维检查', hint: '梳理当前平台问题与优先级', text: '请列出当前平台最需要优先处理的三个问题，并给出原因。' },
  { label: '治理建议', hint: '从风险和管理角度给建议', text: '请从风险视角给出三条平台治理建议。' },
]

const onboardingItems = [
  '上传一份制度文档并查看处理状态。',
  '验证一次关键词检索与混合检索结果。',
  '发起一轮带引用的智能问答。',
  '检查管理页中的运行指标和审计记录。',
  '完成设备登记并验证推送链路。',
]

const hasMessages = computed(() => chatStore.messages.length > 0)
const hasSessions = computed(() => chatStore.sessions.length > 0)
const activeSessionIsDraft = computed(() => chatStore.activeSession?.title === '新对话')
const showHistoryList = computed(() => !hasMessages.value && hasSessions.value && !activeSessionIsDraft.value)
const showHeroState = computed(() => !hasMessages.value && (!hasSessions.value || activeSessionIsDraft.value))
const filteredSessions = computed(() => {
  const keyword = sessionSearch.value.trim().toLowerCase()
  if (!keyword) return chatStore.sessions
  return chatStore.sessions.filter((session) => session.title.toLowerCase().includes(keyword))
})
const lastUserPrompt = computed(() => [...chatStore.messages].reverse().find((msg) => msg.role === 'user')?.content || '')

watch(() => chatStore.messages.length, () => nextTick(() => scrollToBottom()))
watch(() => chatStore.messages[chatStore.messages.length - 1]?.content, () => nextTick(() => scrollToBottom()))

function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg || chatStore.isStreaming) return
  sendMessage(msg, chatStore.activeSessionId)
  inputMessage.value = ''
  nextTick(() => {
    autoResize()
    autoResizeReply()
  })
}

function sendQuickPrompt(prompt: string) {
  inputMessage.value = prompt
  handleSend()
}

function startFreshChat() {
  chatStore.createSession()
}

async function openSession(sessionId: string) {
  await chatStore.setActiveSession(sessionId)
}

function renderMarkdown(text: string) {
  if (!text) return ''
  return marked.parse(text, { breaks: true }) as string
}

function resizeElement(el: HTMLTextAreaElement | null) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function autoResize() {
  resizeElement(inputRef.value)
}

function autoResizeReply() {
  resizeElement(replyInputRef.value)
}

function focusInput() {
  inputRef.value?.focus()
}

function focusReplyInput() {
  replyInputRef.value?.focus()
}

async function submitFeedback(messageId: string, rating: number) {
  try {
    await chatApi.submitFeedback(messageId, rating)
  } catch {
    // Ignore feedback submission errors in the UI.
  }
}

function copyMessage(content: string) {
  navigator.clipboard.writeText(content)
}

function retryLastPrompt() {
  if (lastUserPrompt.value && !chatStore.isStreaming) {
    sendMessage(lastUserPrompt.value, chatStore.activeSessionId)
  }
}

function formatRelativeTime(value: string) {
  const target = new Date(value)
  if (Number.isNaN(target.getTime())) return value
  const diff = Date.now() - target.getTime()
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚更新'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前更新`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前更新`
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前更新`
  return `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}-${String(target.getDate()).padStart(2, '0')}`
}
</script>

<style scoped>
.chat-page {
  min-height: calc(100vh - 120px);
}

.card-shell {
  border: 1px solid var(--border-color);
  border-radius: 28px;
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.section-kicker {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.section-copy {
  margin-top: 10px;
  color: var(--text-secondary);
}

.history-state,
.hero-state,
.conversation-state {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.history-state {
  padding: 18px;
}

.history-header,
.history-toolbar,
.composer-bottom,
.onboarding-header,
.assistant-head,
.assistant-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.history-header h2,
.hero-intro h2 {
  margin-top: 8px;
  font-size: clamp(1.8rem, 1vw + 1.45rem, 2.45rem);
  line-height: 1.1;
  font-family: "Manrope", "PingFang SC", "Microsoft YaHei UI", sans-serif;
}

.history-toolbar {
  margin-top: 18px;
  flex-wrap: wrap;
}

.history-search {
  position: relative;
  flex: 1;
  min-width: 240px;
}

.history-search span {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
}

.history-search-input {
  padding-left: 40px;
}

.history-summary {
  color: var(--text-secondary);
  font-size: 13px;
}

.history-list {
  display: grid;
  gap: 10px;
  margin-top: 22px;
}

.history-item,
.quick-card,
.onboarding-item,
.action-button {
  border: 0;
  background: transparent;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  padding: 18px 20px;
  text-align: left;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.42);
  transition: transform var(--transition-fast), background-color var(--transition-fast), box-shadow var(--transition-fast);
}

.history-item:hover,
.quick-card:hover,
.onboarding-item:hover,
.action-button:hover {
  transform: translateY(-1px);
  background: var(--bg-surface-hover);
}

.history-item strong,
.history-item span,
.history-item small {
  display: block;
}

.history-item span,
.history-item small {
  margin-top: 4px;
  color: var(--text-secondary);
}

.empty-panel {
  padding: 24px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.34);
  color: var(--text-secondary);
}

.empty-panel span {
  display: block;
  margin-top: 8px;
  font-size: 14px;
}

.hero-state {
  max-width: 980px;
  margin: 0 auto;
  padding: 48px 0 24px;
}

.hero-intro {
  max-width: 760px;
}

.hero-composer {
  padding: 20px;
}

.hero-input {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  min-height: 88px;
  background: transparent;
  color: var(--text-primary);
  font-size: 1.05rem;
  line-height: 1.7;
}

.hero-input::placeholder {
  color: var(--text-tertiary);
}

.composer-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}

.composer-plus {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.36);
}

.model-select {
  min-width: 160px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.36);
  padding: 10px 14px;
  color: var(--text-primary);
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.quick-card {
  padding: 18px 20px;
  border-radius: 22px;
  text-align: left;
  background: rgba(255, 255, 255, 0.36);
}

.quick-card strong,
.quick-card span {
  display: block;
}

.quick-card span {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 14px;
}

.onboarding {
  padding: 20px;
}

.onboarding-header {
  margin-bottom: 12px;
  align-items: flex-start;
  flex-direction: column;
}

.onboarding-header span {
  color: var(--text-secondary);
}

.onboarding-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 6px;
  text-align: left;
  border-radius: 16px;
}

.onboarding-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 0 6px var(--color-primary-soft);
}

.conversation-state {
  gap: 16px;
}

.conversation-stream {
  max-width: 920px;
  margin: 0 auto;
  padding: 28px 28px 22px;
}

.message-row + .message-row {
  margin-top: 30px;
}

.message-bubble,
.assistant-copy {
  font-size: 1rem;
  line-height: 1.78;
}

.user-row {
  display: flex;
  justify-content: flex-end;
}

.user-bubble {
  max-width: min(720px, 88%);
  padding: 16px 20px;
  border-radius: 24px;
  background: rgba(36, 31, 23, 0.95);
  color: #fffaf3;
}

.theme-dark .user-bubble {
  background: rgba(245, 238, 227, 0.96);
  color: #17130f;
}

.assistant-head {
  justify-content: flex-start;
  margin-bottom: 12px;
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

.citation-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.citation-pill,
.status-chip {
  display: inline-flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.4);
  border: 1px solid var(--border-color-subtle);
  color: var(--text-secondary);
  font-size: 13px;
}

.assistant-actions {
  justify-content: flex-start;
  flex-wrap: wrap;
  margin-top: 14px;
}

.action-button {
  padding: 8px 12px;
  border-radius: 999px;
  color: var(--text-secondary);
}

.status-line {
  margin-top: 20px;
}

.floating-composer {
  position: sticky;
  bottom: 0;
  max-width: 920px;
  width: 100%;
  margin: 0 auto;
  padding-bottom: 6px;
  background: linear-gradient(180deg, transparent, var(--bg-app) 22%);
}

.compact {
  padding: 16px 18px;
}

.compact .hero-input {
  min-height: 58px;
}

.footer-note {
  margin-top: 10px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

:deep(.markdown-body) {
  color: var(--text-primary);
}

:deep(.markdown-body p + p) {
  margin-top: 12px;
}

:deep(.markdown-body ul),
:deep(.markdown-body ol) {
  padding-left: 20px;
  margin-top: 10px;
}

:deep(.markdown-body code) {
  font-family: var(--font-mono);
  padding: 2px 6px;
  border-radius: 8px;
  background: var(--bg-code);
}

@media (max-width: 900px) {
  .quick-grid {
    grid-template-columns: 1fr;
  }

  .conversation-stream,
  .floating-composer,
  .hero-state {
    max-width: 100%;
  }
}

@media (max-width: 640px) {
  .history-header,
  .history-toolbar,
  .composer-bottom {
    align-items: stretch;
    flex-direction: column;
  }

  .history-state,
  .conversation-stream,
  .hero-composer,
  .onboarding {
    padding: 16px;
  }

  .hero-state {
    padding-top: 16px;
  }
}
</style>

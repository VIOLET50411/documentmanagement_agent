<template>
  <div class="chat-page">
    <section v-if="showHistoryList" class="history-state">
      <div class="history-shell">
        <header class="history-header">
          <div>
            <p class="history-kicker">对话记录</p>
            <h1>会话</h1>
          </div>
          <button class="btn btn-primary btn-lg" @click="startFreshChat">新建对话</button>
        </header>

        <div class="history-search">
          <span class="search-icon">⌕</span>
          <input v-model="sessionSearch" class="history-search-input" placeholder="搜索你的对话记录…" />
        </div>

        <div class="history-meta">
          <span>你在 DocMind 中的历史会话</span>
          <button class="history-select">选择</button>
        </div>

        <div class="history-list">
          <button
            v-for="session in filteredSessions"
            :key="session.id"
            class="history-item"
            @click="openSession(session.id)"
          >
            <strong>{{ session.title }}</strong>
            <span>{{ formatRelativeTime(session.updatedAt) }}</span>
          </button>
          <div v-if="filteredSessions.length === 0" class="history-empty">
            <p>没有匹配的对话记录。</p>
            <p class="history-empty-hint">可以直接新建一轮问答，或换个关键词继续搜索。</p>
          </div>
        </div>
      </div>
    </section>

    <section v-else-if="showHeroState" class="hero-state">
      <div class="hero-title">
        <span class="hero-mark">*</span>
        <h1>DocMind 智能文档工作台</h1>
      </div>

      <div class="composer-card">
        <textarea
          ref="inputRef"
          v-model="inputMessage"
          class="hero-input"
          placeholder="请输入你的问题，例如：总结差旅制度的审批链路，并标注引用位置"
          rows="1"
          :disabled="chatStore.isStreaming"
          @keydown.enter.exact.prevent="handleSend"
          @input="autoResize"
        ></textarea>

        <div class="composer-bottom">
          <button class="composer-plus" @click="focusInput">+</button>
          <div class="composer-meta">
            <label class="model-selector">
              <span class="sr-only">选择模型</span>
              <select v-model="selectedModel" class="model-select">
                <option value="docmind-smart">智能问答模型</option>
                <option value="docmind-retrieval">检索增强模型</option>
                <option value="docmind-brief">精简回答模型</option>
              </select>
            </label>
            <span class="meter">|||</span>
          </div>
        </div>
      </div>

      <div class="quick-actions">
        <button v-for="prompt in quickPrompts" :key="prompt.label" class="quick-chip" @click="sendQuickPrompt(prompt.text)">
          <span>{{ prompt.label }}</span>
        </button>
      </div>

      <div class="setup-card">
        <div class="setup-header">
          <strong>开始使用 DocMind</strong>
          <span>5 项引导</span>
        </div>
        <button v-for="item in onboardingItems" :key="item" class="setup-item" @click="sendQuickPrompt(item)">
          <span class="setup-radio"></span>
          <span>{{ item }}</span>
        </button>
      </div>
    </section>

    <section v-else class="conversation-state">
      <div class="conversation-stream" ref="messagesRef">
        <div v-for="msg in chatStore.messages" :key="msg.id" class="message" :class="msg.role === 'user' ? 'user-card' : 'assistant-card'">
          <div v-if="msg.role === 'user'" class="message-bubble user-bubble">
            <p>{{ msg.content }}</p>
          </div>

          <template v-else>
            <div v-if="msg.content" class="assistant-copy markdown-body" v-html="renderMarkdown(msg.content)"></div>

            <div v-if="msg.citations?.length" class="citation-row">
              <span v-for="cite in msg.citations" :key="`${cite.doc_id}-${cite.page_number}-${cite.section_title}`" class="citation-pill">
                {{ cite.doc_title }} / P{{ cite.page_number ?? '-' }}
              </span>
            </div>

            <div class="assistant-actions">
              <button class="action-icon" title="复制" @click="copyMessage(msg.content)">复制</button>
              <button class="action-icon" title="有帮助" @click="submitFeedback(msg.id, 1)">有帮助</button>
              <button class="action-icon" title="需改进" @click="submitFeedback(msg.id, -1)">需改进</button>
              <button class="action-icon" title="重试" @click="retryLastPrompt">重试</button>
            </div>
          </template>
        </div>

        <div v-if="chatStore.isStreaming && chatStore.streamStatus !== 'streaming'" class="status-line">
          <span class="status-chip">正在处理：{{ chatStore.streamStatusMsg || '准备回答你的问题' }}</span>
        </div>
      </div>

      <div class="floating-composer">
        <div class="composer-card compact">
          <textarea
            ref="replyInputRef"
            v-model="inputMessage"
            class="hero-input"
            placeholder="继续输入你的问题…"
            rows="1"
            :disabled="chatStore.isStreaming"
            @keydown.enter.exact.prevent="handleSend"
            @input="autoResizeReply"
          ></textarea>

          <div class="composer-bottom">
            <button class="composer-plus" @click="focusReplyInput">+</button>
            <div class="composer-meta">
              <label class="model-selector">
                <span class="sr-only">选择模型</span>
                <select v-model="selectedModel" class="model-select">
                  <option value="docmind-smart">智能问答模型</option>
                  <option value="docmind-retrieval">检索增强模型</option>
                  <option value="docmind-brief">精简回答模型</option>
                </select>
              </label>
              <span class="meter">|||</span>
            </div>
          </div>
        </div>

        <p class="footer-note">回答会优先附带引用，请继续核对原始文档内容。</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { marked } from 'marked'
import { useChatStore, type ChatSession } from '@/stores/chat'
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
  { label: '制度问答', text: '请总结当前差旅制度的审批链路。' },
  { label: '检索验证', text: '请说明文档上传后是如何进入检索链路的。' },
  { label: '写作辅助', text: '请起草一份平台实施进展说明。' },
  { label: '运维检查', text: '请列出当前平台最需要优先处理的问题。' },
  { label: '管理建议', text: '请从风险角度给出三条平台治理建议。' },
]

const onboardingItems = [
  '上传一份文档并查看处理状态',
  '验证一次关键词与混合检索结果',
  '发起一轮带引用的智能问答',
  '检查平台管理页中的运行指标',
  '完成个人设置与推送设备登记',
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
  height: 100%;
  overflow-y: auto;
}

.history-state,
.hero-state,
.conversation-state {
  min-height: calc(100vh - 64px);
}

.history-state {
  padding: 32px 28px 42px;
}

.history-shell {
  width: min(1020px, calc(100vw - 240px));
  margin: 0 auto;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 24px;
}

.history-kicker {
  color: var(--text-tertiary);
  font-size: 0.85rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 8px;
}

.history-header h1 {
  font-family: var(--font-serif);
  font-size: clamp(2.4rem, 3vw, 3.2rem);
  letter-spacing: -0.04em;
  line-height: 1;
}

.history-search {
  position: relative;
  display: flex;
  align-items: center;
  border: 1px solid var(--border-color);
  background: color-mix(in srgb, var(--bg-surface-strong) 90%, transparent);
  border-radius: 20px;
  min-height: 56px;
  padding: 0 18px 0 46px;
  box-shadow: 0 8px 26px rgba(34, 29, 24, 0.04);
}

.search-icon {
  position: absolute;
  left: 18px;
  color: var(--text-secondary);
  font-size: 1.2rem;
}

.history-search-input {
  width: 100%;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 1.06rem;
  outline: none;
}

.history-search-input::placeholder {
  color: var(--text-tertiary);
}

.history-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  color: var(--text-secondary);
  margin: 18px 0 12px;
  font-size: 1rem;
}

.history-select {
  border: none;
  background: transparent;
  color: var(--color-info);
  font-size: 1rem;
  cursor: pointer;
  padding: 0;
}

.history-list {
  border-top: 1px solid var(--border-color-subtle);
}

.history-item {
  width: 100%;
  border: none;
  border-bottom: 1px solid var(--border-color-subtle);
  background: transparent;
  padding: 18px 14px;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: background-color var(--transition-fast), padding-left var(--transition-fast);
}

.history-item:hover {
  background: rgba(0, 0, 0, 0.018);
  padding-left: 18px;
}

.theme-dark .history-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.history-item strong {
  font-size: 1.02rem;
  font-weight: 600;
  color: var(--text-primary);
}

.history-item span {
  color: var(--text-secondary);
  font-size: 0.95rem;
}

.history-empty {
  padding: 28px 0;
  color: var(--text-secondary);
}

.history-empty-hint {
  margin-top: 6px;
  color: var(--text-tertiary);
}

.hero-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 96px 24px 40px;
}

.hero-title {
  display: flex;
  align-items: center;
  gap: 14px;
}

.hero-mark {
  color: #e17049;
  font-size: 2.4rem;
  line-height: 1;
}

.hero-title h1 {
  font-family: var(--font-serif);
  font-size: clamp(3rem, 5.2vw, 4.6rem);
  line-height: 1;
  letter-spacing: -0.045em;
  font-weight: 600;
  color: var(--text-primary);
}

.composer-card {
  width: min(980px, calc(100vw - 240px));
  min-height: 154px;
  background: var(--bg-surface-strong);
  border: 1px solid rgba(94, 82, 67, 0.16);
  border-radius: 28px;
  box-shadow: 0 10px 28px rgba(39, 33, 26, 0.05);
  margin-top: 44px;
  padding: 24px 28px 18px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.composer-card.compact {
  width: min(930px, calc(100vw - 220px));
  min-height: 128px;
  margin-top: 0;
}

.hero-input {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-size: 1.02rem;
  line-height: 1.7;
  color: var(--text-primary);
  min-height: 58px;
}

.hero-input::placeholder {
  color: var(--text-tertiary);
}

.composer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
}

.composer-plus {
  border: none;
  background: transparent;
  font-size: 2rem;
  color: var(--text-secondary);
  cursor: pointer;
  line-height: 1;
  padding: 0;
}

.composer-meta {
  display: flex;
  align-items: center;
  gap: 18px;
  color: var(--text-secondary);
}

.model-selector {
  display: inline-flex;
  align-items: center;
}

.model-select {
  border: none;
  background: transparent;
  color: inherit;
  font-size: 0.98rem;
  cursor: pointer;
  outline: none;
  appearance: none;
  padding-right: 18px;
}

.meter {
  letter-spacing: 2px;
  font-weight: 600;
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
  margin-top: 22px;
}

.quick-chip {
  border: 1px solid rgba(94, 82, 67, 0.16);
  background: rgba(255, 255, 252, 0.92);
  border-radius: 16px;
  padding: 10px 16px;
  font-size: 0.96rem;
  color: #4a453e;
  cursor: pointer;
}

.setup-card {
  width: min(820px, calc(100vw - 340px));
  margin-top: 34px;
}

.setup-header {
  display: flex;
  gap: 10px;
  align-items: baseline;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.setup-header strong {
  font-size: 0.98rem;
  color: var(--text-primary);
}

.setup-item {
  width: 100%;
  border: none;
  border-top: 1px solid rgba(94, 82, 67, 0.14);
  background: transparent;
  padding: 18px 0;
  display: flex;
  align-items: center;
  gap: 16px;
  color: var(--text-primary);
  font-size: 1rem;
  text-align: left;
  cursor: pointer;
}

.setup-radio {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid rgba(94, 82, 67, 0.24);
  flex-shrink: 0;
}

.conversation-state {
  display: flex;
  flex-direction: column;
  padding: 20px 24px 40px;
}

.conversation-stream {
  flex: 1;
  width: min(1040px, calc(100vw - 220px));
  margin: 0 auto;
  padding-bottom: 24px;
}

.message {
  display: flex;
  margin-bottom: 26px;
}

.user-card {
  justify-content: flex-end;
}

.assistant-card {
  display: block;
}

.message-bubble {
  max-width: 760px;
  border-radius: 18px;
  padding: 18px 20px;
}

.user-bubble {
  background: rgba(93, 82, 68, 0.06);
  color: var(--text-primary);
  font-size: 0.98rem;
  line-height: 1.6;
}

.assistant-copy {
  max-width: 880px;
  font-size: 1.02rem;
  line-height: 1.8;
  color: var(--text-primary);
}

.assistant-copy :deep(p) {
  margin-bottom: 14px;
}

.assistant-copy :deep(ul),
.assistant-copy :deep(ol) {
  margin: 10px 0 16px;
}

.citation-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.citation-pill {
  border: 1px solid rgba(94, 82, 67, 0.16);
  border-radius: 999px;
  padding: 7px 10px;
  font-size: 0.82rem;
  color: var(--text-secondary);
}

.assistant-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.action-icon {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0;
  font-size: 0.9rem;
}

.status-line {
  margin-bottom: 18px;
}

.status-chip {
  color: var(--text-secondary);
  font-size: 0.94rem;
}

.floating-composer {
  position: sticky;
  bottom: 0;
  padding-top: 18px;
  background: linear-gradient(180deg, rgba(248, 247, 243, 0) 0%, rgba(248, 247, 243, 0.92) 34%, rgba(248, 247, 243, 1) 100%);
}

.theme-dark .floating-composer {
  background: linear-gradient(180deg, rgba(25, 23, 20, 0) 0%, rgba(25, 23, 20, 0.9) 34%, rgba(25, 23, 20, 1) 100%);
}

.floating-composer .composer-card {
  margin-left: auto;
  margin-right: auto;
}

.footer-note {
  text-align: center;
  font-size: 0.9rem;
  color: var(--text-secondary);
  margin-top: 10px;
}

@media (max-width: 900px) {
  .history-state,
  .hero-state,
  .conversation-state {
    padding-left: 16px;
    padding-right: 16px;
  }

  .history-shell,
  .composer-card,
  .composer-card.compact,
  .setup-card,
  .conversation-stream {
    width: 100%;
  }

  .history-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .hero-title h1 {
    font-size: 2.8rem;
  }
}
</style>

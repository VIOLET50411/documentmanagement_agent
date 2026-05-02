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

      <ChatComposer
        class="hero-composer card-shell"
        v-model="inputMessage"
        v-model:selected-model="selectedModel"
        placeholder="请输入问题，例如：总结差旅报销制度的审批链路，并标注引用位置"
        :disabled="chatStore.isStreaming"
        @submit="handleSend"
      />

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
        <MessageList
          :messages="chatStore.messages"
          :runtime-events="chatStore.runtimeEvents"
          :is-streaming="chatStore.isStreaming"
          :stream-status="chatStore.streamStatus"
          :stream-status-msg="chatStore.streamStatusMsg"
          @copy="copyMessage"
          @feedback="submitFeedback"
          @retry="retryLastPrompt"
        />
      </div>

      <SessionTaskBar />

      <div class="floating-composer">
        <ChatComposer
          class="hero-composer compact card-shell"
          v-model="inputMessage"
          v-model:selected-model="selectedModel"
          placeholder="继续追问、补充条件或要求引用更精确的段落"
          :disabled="chatStore.isStreaming"
          compact
          @submit="handleSend"
        />

        <p class="footer-note">回答会优先附带引用。若证据不足，系统会明确提示置信度和原因。</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSSE } from '@/composables/useSSE'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { chatApi } from '@/api/chat'
import MessageList from '@/components/chat/MessageList.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import SessionTaskBar from '@/components/chat/SessionTaskBar.vue'

const chatStore = useChatStore()
const { sendMessage } = useSSE()
const messagesRef = ref<HTMLElement | null>(null)
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
.onboarding-header {
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

.floating-composer {
  position: sticky;
  bottom: 0;
  max-width: 920px;
  width: 100%;
  margin: 0 auto;
  padding-bottom: 6px;
  background: linear-gradient(180deg, transparent, var(--bg-app) 22%);
}

.footer-note {
  margin-top: 10px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
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
  .history-toolbar {
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

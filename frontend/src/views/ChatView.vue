<template>
  <div class="chat-page">
    <section v-if="showHeroState" class="hero-state">
      <div class="hero-intro">
        <h2>您好，今天想了解什么？</h2>
      </div>

      <ChatComposer
        class="hero-composer"
        v-model="inputMessage"
        v-model:selected-model="selectedModel"
        placeholder="How can I help you today?"
        :disabled="chatStore.isStreaming"
        @submit="handleSend"
      />

      <div class="quick-pills">
        <button v-for="prompt in quickPrompts" :key="prompt.label" class="quick-pill" @click="sendQuickPrompt(prompt.text)">
          <span class="pill-icon">✧</span>
          <span>{{ prompt.label }}</span>
        </button>
      </div>
    </section>

    <section v-else class="conversation-state">
      <div class="conversation-stream" ref="messagesRef">
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

const chatStore = useChatStore()
const { sendMessage } = useSSE()
const messagesRef = ref<HTMLElement | null>(null)
const inputMessage = ref('')
const sessionSearch = ref('')
const selectedModel = ref('qwen2.5:1.5b')
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
const showHeroState = computed(() => !hasMessages.value)
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
  sendMessage(msg, chatStore.activeSessionId, selectedModel.value)
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
    sendMessage(lastUserPrompt.value, chatStore.activeSessionId, selectedModel.value)
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
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
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
  font-size: clamp(2rem, 2.5vw + 1rem, 3rem);
  line-height: 1.2;
  font-family: var(--font-heading);
  font-weight: 400;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
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
.action-button {
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  transition: all var(--transition-fast);
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  padding: 16px 20px;
  text-align: left;
  border-radius: var(--radius-md);
}

.history-item:hover,
.action-button:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-color-strong);
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
  border-radius: var(--radius-md);
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.empty-panel span {
  display: block;
  margin-top: 8px;
  font-size: 14px;
}

.hero-state {
  max-width: 900px;
  margin: 0 auto;
  padding: 10vh 0 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.hero-intro {
  margin-bottom: 24px;
}

.quick-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 16px;
}

.quick-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 14px;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.quick-pill:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  border-color: var(--border-color-strong);
}

.conversation-state {
  gap: 16px;
}

.conversation-stream {
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
  padding: 28px 0 22px;
}

.floating-composer {
  position: sticky;
  bottom: 0;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
  padding-bottom: 24px;
  background: linear-gradient(180deg, transparent, var(--bg-app) 24px);
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

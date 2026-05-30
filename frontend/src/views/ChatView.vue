<template>
  <div class="chat-page" @keydown="handleGlobalKeydown">
    <section v-if="showHeroState" class="hero-state">
      <div class="hero-intro">
        <h2>{{ heroTitle }}</h2>
      </div>

      <ChatComposer
        ref="heroComposerRef"
        class="hero-composer"
        v-model="inputMessage"
        v-model:selected-model="selectedModel"
        :placeholder="heroPlaceholder"
        :disabled="chatStore.isStreaming"
        @submit="handleSend"
      />

      <div class="quick-pills">
        <button v-for="prompt in quickPrompts" :key="prompt.label" class="quick-pill" @click="sendQuickPrompt(prompt.text)">
          <span class="pill-icon">+</span>
          <span>{{ prompt.label }}</span>
        </button>
      </div>

    </section>

    <section v-else class="conversation-state">
      <div class="conversation-stream" ref="messagesRef">
        <!-- Skeleton loading -->
        <div v-if="isLoadingHistory" class="skeleton-wrapper">
          <div class="skeleton-bubble skeleton-user"><div class="skeleton-line w60"></div></div>
          <div class="skeleton-bubble skeleton-assistant">
            <div class="skeleton-line w90"></div>
            <div class="skeleton-line w75"></div>
            <div class="skeleton-line w40"></div>
          </div>
          <div class="skeleton-bubble skeleton-user"><div class="skeleton-line w50"></div></div>
          <div class="skeleton-bubble skeleton-assistant">
            <div class="skeleton-line w85"></div>
            <div class="skeleton-line w65"></div>
          </div>
        </div>
        <MessageList
          v-else
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

      <!-- Scroll to bottom FAB -->
      <transition name="fab-fade">
        <button v-if="!isAtBottom && hasMessages" class="scroll-fab" @click="scrollToBottom()" title="返回最新消息">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <polyline points="19 12 12 19 5 12"></polyline>
          </svg>
        </button>
      </transition>

      <div class="floating-composer">
        <ChatComposer
          ref="convComposerRef"
          class="hero-composer compact card-shell"
          v-model="inputMessage"
          v-model:selected-model="selectedModel"
          :placeholder="followupPlaceholder"
          :disabled="chatStore.isStreaming"
          compact
          @submit="handleSend"
        />

        <p class="footer-note">{{ footerNote }}</p>
      </div>
    </section>

    <!-- Search Panel -->
    <transition name="panel-slide">
      <aside v-if="searchPanelOpen" class="search-panel">
        <div class="search-panel-header">
          <span class="search-panel-title">知识检索</span>
          <button class="search-panel-close" @click="searchPanelOpen = false" title="关闭">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <div class="search-panel-body">
          <div class="search-input-row">
            <input v-model="searchQuery" class="search-input" placeholder="输入关键词检索知识库..." @keydown.enter="doSearch" />
            <select v-model="searchType" class="search-type-select">
              <option value="hybrid">混合</option>
              <option value="vector">向量</option>
              <option value="keyword">关键词</option>
              <option value="graph">图谱</option>
            </select>
            <button class="search-go-btn" @click="doSearch" :disabled="isSearching || !searchQuery.trim()">检索</button>
          </div>
          <div v-if="isSearching" class="search-loading">正在检索...</div>
          <div v-else-if="searchResults.length" class="search-results">
            <div v-for="(result, idx) in searchResults" :key="idx" class="search-result-card">
              <div class="search-result-head">
                <span class="search-result-rank">#{{ idx + 1 }}</span>
                <span class="search-result-title">{{ result.doc_title || result.document_title || '未命名文档' }}</span>
                <span class="search-result-score">{{ (result.score || result.rrf_score || 0).toFixed(3) }}</span>
              </div>
              <p class="search-result-snippet">{{ result.snippet || result.content || '' }}</p>
              <div v-if="result.section_title || result.page_number" class="search-result-meta">
                <span v-if="result.section_title">{{ result.section_title }}</span>
                <span v-if="result.page_number">页码 {{ result.page_number }}</span>
              </div>
            </div>
          </div>
          <div v-else-if="searchDone" class="search-empty">未找到相关结果</div>
        </div>
      </aside>
    </transition>

    <!-- Search toggle button (fixed) -->
    <button class="search-toggle-btn" @click="searchPanelOpen = !searchPanelOpen" :class="{ active: searchPanelOpen }" title="知识检索面板">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    </button>

    <!-- Toast notifications -->
    <transition name="toast-slide">
      <div v-if="toastMessage" class="toast-notification" :class="toastType">
        {{ toastMessage }}
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue"
import { useChatStore } from "@/stores/chat"
import { useSSE } from "@/composables/useSSE"
import { useAutoScroll } from "@/composables/useAutoScroll"
import { chatApi } from "@/api/chat"
import { searchApi } from "@/api/search"
import MessageList from "@/components/chat/MessageList.vue"
import ChatComposer from "@/components/chat/ChatComposer.vue"

const heroTitle = "您好，今天想了解什么？"
const heroPlaceholder = "请直接提问，或描述你要检索、总结、对比的文档问题"
const followupPlaceholder = "继续追问、补充条件，或要求引用更精确的段落"
const footerNote = "回答会优先附带引用。若证据不足，系统会明确提示可信度和原因。"

const chatStore = useChatStore()
const { sendMessage } = useSSE()
const messagesRef = ref<HTMLElement | null>(null)
const heroComposerRef = ref<InstanceType<typeof ChatComposer> | null>(null)
const convComposerRef = ref<InstanceType<typeof ChatComposer> | null>(null)
const inputMessage = ref("")
const selectedModel = ref("qwen2.5:1.5b")
const isLoadingHistory = ref(false)
const { isAtBottom, scrollToBottom } = useAutoScroll(messagesRef)

// Search panel state
const searchPanelOpen = ref(false)
const searchQuery = ref("")
const searchType = ref("hybrid")
const searchResults = ref<any[]>([])
const isSearching = ref(false)
const searchDone = ref(false)

// Toast state
const toastMessage = ref("")
const toastType = ref("info")
let toastTimer: ReturnType<typeof setTimeout> | null = null

const quickPrompts = [
  { label: "制度问答", text: "请总结当前差旅制度的审批链路，并说明各角色职责。" },
  { label: "检索验证", text: "请说明文档上传后是如何进入检索链路的。" },
  { label: "写作辅助", text: "请起草一份平台实施进展说明，包含风险与下一步计划。" },
  { label: "运维检查", text: "请列出当前平台最需要优先处理的三个问题，并给出原因。" },
  { label: "治理建议", text: "请从风险视角给出三条平台治理建议。" },
]

const hasMessages = computed(() => chatStore.messages.length > 0)
const showHeroState = computed(() => !hasMessages.value)
const lastUserPrompt = computed(() => [...chatStore.messages].reverse().find((msg) => msg.role === "user")?.content || "")

onMounted(async () => {
  isLoadingHistory.value = true
  try {
    await chatStore.initialize({ loadActiveHistory: true })
    await chatStore.ensureActiveSessionLoaded()
  } finally {
    isLoadingHistory.value = false
  }
})

// Show skeleton when switching sessions
watch(() => chatStore.activeSessionId, async (newId, oldId) => {
  if (newId && newId !== oldId && chatStore.messages.length === 0) {
    isLoadingHistory.value = true
    await nextTick()
    setTimeout(() => { isLoadingHistory.value = false }, 300)
  }
})
watch(() => chatStore.messages.length, () => {
  if (isAtBottom.value) nextTick(() => scrollToBottom())
})
watch(() => chatStore.messages[chatStore.messages.length - 1]?.content, () => {
  if (isAtBottom.value) nextTick(() => scrollToBottom())
})

onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer)
})

function showToast(message: string, type: "info" | "success" | "error" = "info", duration = 2500) {
  toastMessage.value = message
  toastType.value = type
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastMessage.value = "" }, duration)
}

function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg || chatStore.isStreaming) return
  sendMessage(msg, chatStore.activeSessionId, selectedModel.value)
  inputMessage.value = ""
  nextTick(() => {
    convComposerRef.value?.focusInput()
  })
}

function sendQuickPrompt(prompt: string) {
  inputMessage.value = prompt
  handleSend()
}

async function submitFeedback(messageId: string, rating: number) {
  try {
    await chatApi.submitFeedback(messageId, rating)
    showToast(rating > 0 ? "感谢反馈！" : "已记录，我们会持续改进", "success")
  } catch {
    showToast("反馈提交失败", "error")
  }
}

function copyMessage(content: string) {
  navigator.clipboard.writeText(content).then(
    () => showToast("已复制到剪贴板", "success"),
    () => showToast("复制失败", "error"),
  )
}

function retryLastPrompt() {
  if (lastUserPrompt.value && !chatStore.isStreaming) {
    // Remove the failed assistant message before retrying
    const lastMsg = chatStore.messages[chatStore.messages.length - 1]
    if (lastMsg && lastMsg.role === "assistant") {
      chatStore.removeLastMessage()
    }
    sendMessage(lastUserPrompt.value, chatStore.activeSessionId, selectedModel.value)
  }
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  isSearching.value = true
  searchDone.value = false
  searchResults.value = []
  try {
    const res = await searchApi.search(q, { search_type: searchType.value, top_k: 10 })
    searchResults.value = res.results || []
  } catch {
    showToast("检索失败，请稍后重试", "error")
  } finally {
    isSearching.value = false
    searchDone.value = true
  }
}

function handleGlobalKeydown(e: KeyboardEvent) {
  // Escape closes search panel
  if (e.key === "Escape" && searchPanelOpen.value) {
    searchPanelOpen.value = false
    e.preventDefault()
  }
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

.section-copy {
  max-width: 640px;
  margin: 16px auto 0;
  color: var(--text-secondary);
  font-size: 1.05rem;
  line-height: 1.7;
}

.hero-state,
.conversation-state {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.hero-intro h2 {
  font-size: clamp(2.2rem, 3.5vw + 1.2rem, 3.2rem);
  line-height: 1.25;
  font-family: var(--font-heading);
  font-weight: 700;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, var(--text-primary) 30%, var(--color-primary) 100%);
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.hero-state {
  max-width: 900px;
  margin: 0 auto;
  padding: 8vh 0 24px;
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
  margin-top: 24px;
}

.quick-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-color-strong);
  background: var(--bg-sidebar);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  color: var(--text-secondary);
  font-size: 13.5px;
  font-weight: 500;
  transition: all var(--transition-base);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
}

.quick-pill:hover {
  background: var(--bg-surface-strong);
  color: var(--color-primary);
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.04);
}

.pill-icon {
  font-size: 14px;
  color: var(--color-primary);
  transition: transform var(--transition-fast);
}

.quick-pill:hover .pill-icon {
  transform: rotate(90deg) scale(1.1);
}

.capability-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  align-items: center;
  gap: 18px;
  margin-top: 20px;
}

.capability-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 500;
}

.capability-chip::before {
  content: "";
  display: inline-block;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--color-primary);
  opacity: 0.7;
}

.capability-note {
  max-width: 680px;
  margin: 32px auto 0;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.65;
  padding-top: 16px;
  border-top: 1px dashed var(--border-color);
  opacity: 0.85;
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
  font-size: 12px;
}

/* Skeleton Loading */
.skeleton-wrapper {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 20px 0;
  max-width: 900px;
  margin: 0 auto;
}

.skeleton-bubble {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 20px;
  border-radius: 16px;
  max-width: 70%;
}

.skeleton-user {
  align-self: flex-end;
  background: rgba(217, 119, 87, 0.08);
}

.skeleton-assistant {
  align-self: flex-start;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
}

.skeleton-line {
  height: 12px;
  border-radius: 6px;
  background: linear-gradient(90deg, var(--border-color) 25%, var(--border-color-subtle, rgba(255,255,255,0.15)) 50%, var(--border-color) 75%);
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
}

.skeleton-line.w90 { width: 90%; }
.skeleton-line.w85 { width: 85%; }
.skeleton-line.w75 { width: 75%; }
.skeleton-line.w65 { width: 65%; }
.skeleton-line.w60 { width: 60%; }
.skeleton-line.w50 { width: 50%; }
.skeleton-line.w40 { width: 40%; }

@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@media (max-width: 900px) {
  .conversation-stream,
  .floating-composer,
  .hero-state {
    max-width: 100%;
  }
}

@media (max-width: 640px) {
  .conversation-stream,
  .hero-composer {
    padding: 16px;
  }

  .hero-state {
    padding-top: 16px;
  }
}

/* Scroll to bottom FAB */
.scroll-fab {
  position: fixed;
  bottom: 120px;
  right: 32px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  cursor: pointer;
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: all var(--transition-fast);
  z-index: 50;
}

.scroll-fab:hover {
  background: var(--color-primary);
  color: var(--text-on-primary);
  transform: scale(1.1);
  box-shadow: 0 6px 20px rgba(217, 119, 87, 0.25);
}

.fab-fade-enter-active,
.fab-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fab-fade-enter-from,
.fab-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* Search Panel */
.search-toggle-btn {
  position: fixed;
  top: 72px;
  right: 24px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all var(--transition-fast);
  z-index: 60;
  box-shadow: var(--shadow-sm);
}

.search-toggle-btn:hover,
.search-toggle-btn.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.search-panel {
  position: fixed;
  top: 60px;
  right: 0;
  bottom: 0;
  width: 380px;
  max-width: 100vw;
  background: var(--bg-sidebar);
  border-left: 1px solid var(--border-color);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  z-index: 55;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.06);
}

.search-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.search-panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.search-panel-close {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.search-panel-close:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}

.search-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-input-row {
  display: flex;
  gap: 8px;
}

.search-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color var(--transition-fast);
}

.search-input:focus {
  border-color: var(--color-primary);
}

.search-type-select {
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 12px;
  outline: none;
  cursor: pointer;
}

.search-go-btn {
  padding: 8px 16px;
  border: 0;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: var(--text-on-primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.search-go-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.search-go-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.search-loading {
  text-align: center;
  padding: 24px;
  color: var(--text-tertiary);
  font-size: 13px;
}

.search-results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.search-result-card {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  transition: border-color var(--transition-fast);
}

.search-result-card:hover {
  border-color: var(--border-color-strong);
}

.search-result-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.search-result-rank {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-primary);
  min-width: 22px;
}

.search-result-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.search-result-score {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: monospace;
}

.search-result-snippet {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.search-result-meta {
  display: flex;
  gap: 12px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.search-empty {
  text-align: center;
  padding: 24px;
  color: var(--text-tertiary);
  font-size: 13px;
}

.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: transform 0.25s ease, opacity 0.25s ease;
}
.panel-slide-enter-from,
.panel-slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

/* Toast Notifications */
.toast-notification {
  position: fixed;
  bottom: 32px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 24px;
  border-radius: var(--radius-full);
  font-size: 13px;
  font-weight: 500;
  z-index: 200;
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.toast-notification.info {
  background: var(--bg-surface-strong);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.toast-notification.success {
  background: rgba(34, 197, 94, 0.15);
  color: var(--color-success, #22c55e);
  border: 1px solid rgba(34, 197, 94, 0.25);
}

.toast-notification.error {
  background: rgba(239, 68, 68, 0.15);
  color: var(--color-danger, #ef4444);
  border: 1px solid rgba(239, 68, 68, 0.25);
}

.toast-slide-enter-active,
.toast-slide-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}
.toast-slide-enter-from {
  opacity: 0;
  transform: translateX(-50%) translateY(12px);
}
.toast-slide-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-8px);
}
</style>

<template>
  <div class="chat-page">
    <section v-if="showHeroState" class="hero-state">
      <div class="hero-intro">
        <h2>{{ heroTitle }}</h2>
        <p class="section-copy">{{ heroDescription }}</p>
      </div>

      <ChatComposer
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
          :placeholder="followupPlaceholder"
          :disabled="chatStore.isStreaming"
          compact
          @submit="handleSend"
        />

        <p class="footer-note">{{ footerNote }}</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue"
import { useChatStore } from "@/stores/chat"
import { useSSE } from "@/composables/useSSE"
import { useAutoScroll } from "@/composables/useAutoScroll"
import { chatApi } from "@/api/chat"
import MessageList from "@/components/chat/MessageList.vue"
import ChatComposer from "@/components/chat/ChatComposer.vue"

const heroTitle = "\u60a8\u597d\uff0c\u4eca\u5929\u60f3\u4e86\u89e3\u4ec0\u4e48\uff1f"
const heroDescription =
  "\u6211\u662f\u60a8\u7684\u667a\u80fd\u6587\u6863\u52a9\u624b\u3002\u6211\u53ef\u4ee5\u5e2e\u60a8\u603b\u7ed3\u957f\u6587\u6863\u3001\u68c0\u7d22\u5173\u952e\u4fe1\u606f\uff0c\u5e76\u57fa\u4e8e\u4f01\u4e1a\u77e5\u8bc6\u5e93\u56de\u7b54\u95ee\u9898\u3002\u8bf7\u5728\u4e0b\u65b9\u76f4\u63a5\u63d0\u95ee\uff0c\u6216\u9009\u62e9\u5feb\u6377\u6307\u4ee4\u5f00\u59cb\u3002"
const heroPlaceholder =
  "\u8bf7\u76f4\u63a5\u63d0\u95ee\uff0c\u6216\u63cf\u8ff0\u4f60\u8981\u68c0\u7d22\u3001\u603b\u7ed3\u3001\u5bf9\u6bd4\u7684\u6587\u6863\u95ee\u9898"
const followupPlaceholder =
  "\u7ee7\u7eed\u8ffd\u95ee\u3001\u8865\u5145\u6761\u4ef6\uff0c\u6216\u8981\u6c42\u5f15\u7528\u66f4\u7cbe\u786e\u7684\u6bb5\u843d"
const footerNote =
  "\u56de\u7b54\u4f1a\u4f18\u5148\u9644\u5e26\u5f15\u7528\u3002\u82e5\u8bc1\u636e\u4e0d\u8db3\uff0c\u7cfb\u7edf\u4f1a\u660e\u786e\u63d0\u793a\u7f6e\u4fe1\u5ea6\u548c\u539f\u56e0\u3002"

const chatStore = useChatStore()
const { sendMessage } = useSSE()
const messagesRef = ref<HTMLElement | null>(null)
const inputMessage = ref("")
const selectedModel = ref("qwen2.5:1.5b")
const { scrollToBottom } = useAutoScroll(messagesRef)

const quickPrompts = [
  {
    label: "\u5236\u5ea6\u95ee\u7b54",
    text: "\u8bf7\u603b\u7ed3\u5f53\u524d\u5dee\u65c5\u5236\u5ea6\u7684\u5ba1\u6279\u94fe\u8def\uff0c\u5e76\u8bf4\u660e\u5404\u89d2\u8272\u804c\u8d23\u3002",
  },
  {
    label: "\u68c0\u7d22\u9a8c\u8bc1",
    text: "\u8bf7\u8bf4\u660e\u6587\u6863\u4e0a\u4f20\u540e\u662f\u5982\u4f55\u8fdb\u5165\u68c0\u7d22\u94fe\u8def\u7684\u3002",
  },
  {
    label: "\u5199\u4f5c\u8f85\u52a9",
    text: "\u8bf7\u8d77\u8349\u4e00\u4efd\u5e73\u53f0\u5b9e\u65bd\u8fdb\u5c55\u8bf4\u660e\uff0c\u5305\u542b\u98ce\u9669\u4e0e\u4e0b\u4e00\u6b65\u8ba1\u5212\u3002",
  },
  {
    label: "\u8fd0\u7ef4\u68c0\u67e5",
    text: "\u8bf7\u5217\u51fa\u5f53\u524d\u5e73\u53f0\u6700\u9700\u8981\u4f18\u5148\u5904\u7406\u7684\u4e09\u4e2a\u95ee\u9898\uff0c\u5e76\u7ed9\u51fa\u539f\u56e0\u3002",
  },
  {
    label: "\u6cbb\u7406\u5efa\u8bae",
    text: "\u8bf7\u4ece\u98ce\u9669\u89c6\u89d2\u7ed9\u51fa\u4e09\u6761\u5e73\u53f0\u6cbb\u7406\u5efa\u8bae\u3002",
  },
]

const hasMessages = computed(() => chatStore.messages.length > 0)
const showHeroState = computed(() => !hasMessages.value)
const lastUserPrompt = computed(() => [...chatStore.messages].reverse().find((msg) => msg.role === "user")?.content || "")

watch(() => chatStore.messages.length, () => nextTick(() => scrollToBottom()))
watch(() => chatStore.messages[chatStore.messages.length - 1]?.content, () => nextTick(() => scrollToBottom()))

function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg || chatStore.isStreaming) return
  sendMessage(msg, chatStore.activeSessionId, selectedModel.value)
  inputMessage.value = ""
}

function sendQuickPrompt(prompt: string) {
  inputMessage.value = prompt
  handleSend()
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
  margin-top: 10px;
  color: var(--text-secondary);
}

.hero-state,
.conversation-state {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

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
</style>

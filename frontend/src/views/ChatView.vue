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

      <div class="capability-strip">
        <span v-for="item in capabilityChips" :key="item" class="capability-chip">{{ item }}</span>
      </div>

      <p class="capability-note">{{ capabilityNote }}</p>
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
import { computed, nextTick, onMounted, ref, watch } from "vue"
import { useChatStore } from "@/stores/chat"
import { useSSE } from "@/composables/useSSE"
import { useAutoScroll } from "@/composables/useAutoScroll"
import { chatApi } from "@/api/chat"
import MessageList from "@/components/chat/MessageList.vue"
import ChatComposer from "@/components/chat/ChatComposer.vue"

const heroTitle = "您好，今天想了解什么？"
const heroDescription =
  "我是您的智能文档助手。我可以帮助您总结长文档、检索关键信息，并基于企业知识库回答问题。请直接提问，或选择下方快捷指令开始。"
const heroPlaceholder = "请直接提问，或描述你要检索、总结、对比的文档问题"
const followupPlaceholder = "继续追问、补充条件，或要求引用更精确的段落"
const footerNote = "回答会优先附带引用。若证据不足，系统会明确提示可信度和原因。"
const capabilityNote =
  "当前版本支持知识库检索、结构化摘要、字段提取、流程/对比问答、统计查询与运行轨迹展示；暂不直接修改本机文件，也不执行桌面自动化操作。"

const chatStore = useChatStore()
const { sendMessage } = useSSE()
const messagesRef = ref<HTMLElement | null>(null)
const inputMessage = ref("")
const selectedModel = ref("qwen2.5:1.5b")
const { scrollToBottom } = useAutoScroll(messagesRef)

const quickPrompts = [
  {
    label: "制度问答",
    text: "请总结当前差旅制度的审批链路，并说明各角色职责。",
  },
  {
    label: "检索验证",
    text: "请说明文档上传后是如何进入检索链路的。",
  },
  {
    label: "写作辅助",
    text: "请起草一份平台实施进展说明，包含风险与下一步计划。",
  },
  {
    label: "运维检查",
    text: "请列出当前平台最需要优先处理的三个问题，并给出原因。",
  },
  {
    label: "治理建议",
    text: "请从风险视角给出三条平台治理建议。",
  },
]

const capabilityChips = [
  "知识检索与引用",
  "文档摘要与字段提取",
  "流程 / 对比问答",
  "统计查询",
  "工具调用轨迹",
]

const hasMessages = computed(() => chatStore.messages.length > 0)
const showHeroState = computed(() => !hasMessages.value)
const lastUserPrompt = computed(() => [...chatStore.messages].reverse().find((msg) => msg.role === "user")?.content || "")

onMounted(() => {
  void chatStore.initialize({ loadActiveHistory: true })
  void chatStore.ensureActiveSessionLoaded()
})

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

.capability-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 8px;
}

.capability-chip {
  display: inline-flex;
  align-items: center;
  padding: 7px 12px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--bg-surface) 92%, transparent);
  border: 1px solid var(--border-color-subtle);
  color: var(--text-secondary);
  font-size: 13px;
}

.capability-note {
  max-width: 760px;
  margin: 0;
  color: var(--text-tertiary);
  font-size: 13px;
  line-height: 1.65;
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

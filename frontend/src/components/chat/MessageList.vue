<template>
  <div class="message-list">
    <RuntimeEventList v-if="runtimeEvents.length" :events="runtimeEvents" />

    <div
      v-for="(msg, index) in messages"
      :key="msg.id"
      class="message-row"
      :class="msg.role === 'user' ? 'user-message-row' : 'assistant-message-row'"
      ref="messageRefs"
    >
      <template v-if="visibleSet.has(index) || index >= messages.length - 6">
        <UserMessage v-if="msg.role === 'user'" :message="msg" />
        <AssistantMessage
          v-else
          :message="msg"
          :is-streaming="isStreaming && index === messages.length - 1"
          @copy="$emit('copy', $event)"
          @feedback="(messageId, rating) => $emit('feedback', messageId, rating)"
          @retry="$emit('retry')"
        />
      </template>
      <div v-else class="message-placeholder" :style="{ minHeight: '60px' }"></div>
    </div>

    <div v-if="isStreaming && streamStatus !== 'streaming'" class="status-line">
      <span class="status-chip">{{ streamStatusMsg || preparingMessage }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue"
import type { ChatMessage, ChatRuntimeEvent } from "@/stores/chat"
import AssistantMessage from "./AssistantMessage.vue"
import RuntimeEventList from "./RuntimeEventList.vue"
import UserMessage from "./UserMessage.vue"

const preparingMessage = "\u6b63\u5728\u51c6\u5907\u56de\u7b54\uff0c\u8bf7\u7a0d\u5019\u2026"

const props = defineProps<{
  messages: ChatMessage[]
  runtimeEvents: ChatRuntimeEvent[]
  isStreaming: boolean
  streamStatus: string
  streamStatusMsg: string
}>()

defineEmits<{
  copy: [content: string]
  feedback: [messageId: string, rating: number]
  retry: []
}>()

const messageRefs = ref<HTMLElement[]>([])
const visibleSet = ref<Set<number>>(new Set())
let observer: IntersectionObserver | null = null

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const idx = messageRefs.value.indexOf(entry.target as HTMLElement)
        if (idx === -1) continue
        if (entry.isIntersecting) {
          visibleSet.value.add(idx)
        } else {
          // Keep recently visible messages for scroll stability
          if (idx < props.messages.length - 10) {
            visibleSet.value.delete(idx)
          }
        }
      }
    },
    { rootMargin: "200px 0px" }
  )
  observeAll()
})

watch(() => props.messages.length, () => {
  observeAll()
  // Always mark newest messages as visible
  for (let i = Math.max(0, props.messages.length - 6); i < props.messages.length; i++) {
    visibleSet.value.add(i)
  }
})

function observeAll() {
  if (!observer) return
  for (const el of messageRefs.value) {
    if (el) observer.observe(el)
  }
}

onBeforeUnmount(() => {
  observer?.disconnect()
})
</script>

<style scoped>
.message-row + .message-row {
  margin-top: 30px;
}

.status-line {
  margin-top: 20px;
}

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

.message-placeholder {
  border-radius: 12px;
  background: transparent;
}
</style>

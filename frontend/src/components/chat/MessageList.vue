<template>
  <div class="message-list">
    <RuntimeEventList v-if="runtimeEvents.length" :events="runtimeEvents" />

    <div
      v-for="(msg, index) in messages"
      :key="msg.id"
      class="message-row"
      :class="msg.role === 'user' ? 'user-message-row' : 'assistant-message-row'"
    >
      <UserMessage v-if="msg.role === 'user'" :message="msg" />
      <AssistantMessage
        v-else
        :message="msg"
        :is-streaming="isStreaming && index === messages.length - 1"
        @copy="$emit('copy', $event)"
        @feedback="(messageId, rating) => $emit('feedback', messageId, rating)"
        @retry="$emit('retry')"
      />
    </div>

    <div v-if="isStreaming && streamStatus !== 'streaming'" class="status-line">
      <span class="status-chip">{{ streamStatusMsg || "正在准备回答，请稍候…" }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage, ChatRuntimeEvent } from "@/stores/chat"
import AssistantMessage from "./AssistantMessage.vue"
import RuntimeEventList from "./RuntimeEventList.vue"
import UserMessage from "./UserMessage.vue"

defineProps<{
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
</style>

<template>
  <div class="user-row">
    <div class="user-bubble">
      <p>{{ message.content }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage } from "@/stores/chat"

defineProps<{
  message: ChatMessage
}>()
</script>

<style scoped>
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
  box-shadow: 0 18px 40px rgba(41, 32, 15, 0.18);
}

.theme-dark .user-bubble {
  background: rgba(245, 238, 227, 0.96);
  color: #17130f;
}

.user-bubble p {
  margin: 0;
  font-size: 1rem;
  line-height: 1.78;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

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
  max-width: min(1200px, 88%);
  padding: 12px 18px;
  border-radius: 20px;
  background: var(--bg-surface-strong);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
}

.theme-dark .user-bubble {
  background: var(--bg-surface-strong);
  color: var(--text-primary);
}

.user-bubble p {
  margin: 0;
  font-size: 1rem;
  line-height: 1.78;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

<template>
  <div v-if="event.degraded && event.fallbackReason" class="fallback-notice">
    <strong>{{ title }}</strong>
    <span>{{ event.fallbackReason }}</span>
  </div>
</template>

<script setup lang="ts">
import type { ChatRuntimeEvent } from "@/stores/chat"

const title = "\u5df2\u89e6\u53d1\u964d\u7ea7\u8def\u5f84"

defineProps<{
  event: ChatRuntimeEvent
}>()
</script>

<style scoped>
.fallback-notice {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(217, 45, 32, 0.2);
  background: rgba(255, 244, 243, 0.8);
  color: #b42318;
  font-size: 13px;
}
</style>

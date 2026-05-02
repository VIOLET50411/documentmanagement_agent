<template>
  <article class="tool-card" :data-degraded="event.degraded ? 'true' : 'false'">
    <div class="tool-head">
      <div class="tool-title-row">
        <span class="tool-icon">调</span>
        <div>
          <strong>工具调用</strong>
          <p class="tool-source">{{ event.source || "agent_runtime_v2" }}</p>
        </div>
      </div>
      <span class="tool-seq">#{{ event.sequenceNum ?? "-" }}</span>
    </div>

    <p class="tool-message">{{ event.message }}</p>

    <div class="tool-meta">
      <span v-if="event.traceId">Trace：{{ event.traceId }}</span>
      <span>{{ formatTime(event.timestamp) }}</span>
    </div>

    <p v-if="event.degraded && event.fallbackReason" class="tool-fallback">
      已降级：{{ event.fallbackReason }}
    </p>
  </article>
</template>

<script setup lang="ts">
import type { ChatRuntimeEvent } from "@/stores/chat"

defineProps<{
  event: ChatRuntimeEvent
}>()

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "--:--"
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`
}
</script>

<style scoped>
.tool-card {
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(126, 34, 206, 0.18);
  background: rgba(255, 255, 255, 0.42);
}

.tool-card[data-degraded="true"] {
  border-color: rgba(217, 45, 32, 0.2);
  background: rgba(255, 247, 245, 0.82);
}

.tool-head,
.tool-title-row,
.tool-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tool-head {
  justify-content: space-between;
}

.tool-icon {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(126, 34, 206, 0.14);
  color: #7e22ce;
  font-size: 12px;
  font-weight: 700;
}

.tool-source,
.tool-meta,
.tool-seq {
  color: var(--text-tertiary);
  font-size: 12px;
}

.tool-message {
  margin: 12px 0 0;
  color: var(--text-primary);
  line-height: 1.65;
}

.tool-meta {
  flex-wrap: wrap;
  margin-top: 12px;
}

.tool-fallback {
  margin-top: 10px;
  color: #b42318;
  font-size: 13px;
}
</style>

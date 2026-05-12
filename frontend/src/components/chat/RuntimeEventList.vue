<template>
  <div v-if="events.length" class="runtime-shell">
    <button class="runtime-toggle" type="button" @click="expanded = !expanded">
      <div class="runtime-head">
        <span class="runtime-title">
          {{ runtimeTitle }}
          <span v-if="activeEvent" class="runtime-live-dots" aria-hidden="true"></span>
        </span>
        <span class="runtime-count">{{ events.length }} {{ stageUnit }}</span>
        <span class="runtime-expand">{{ expanded ? collapseLabel : expandLabel }}</span>
      </div>
      <p v-if="!expanded" class="runtime-preview">{{ previewText }}</p>
    </button>

    <transition name="runtime-collapse">
      <div v-if="expanded" class="runtime-list">
        <template v-for="event in events" :key="event.id">
          <ToolCallBlock v-if="event.status === 'tool_call'" :event="event" />
          <article v-else class="runtime-card" :data-status="event.status">
            <div class="runtime-card-head">
              <div class="runtime-card-label">
                <span class="runtime-icon">{{ statusIcon(event.status) }}</span>
                <strong>{{ statusLabel(event.status) }}</strong>
              </div>
              <span class="runtime-time">
                {{ isActiveEvent(event) ? runningLabel : formatTime(event.timestamp) }}
              </span>
            </div>
            <p class="runtime-message">{{ event.message }}</p>
            <div class="runtime-meta">
              <span v-if="event.source">{{ event.source }}</span>
              <span v-if="event.sequenceNum">#{{ event.sequenceNum }}</span>
              <span v-if="event.traceId">Trace: {{ event.traceId }}</span>
            </div>
            <FallbackNotice :event="event" />
          </article>
        </template>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import type { ChatRuntimeEvent } from "@/stores/chat"
import FallbackNotice from "./FallbackNotice.vue"
import ToolCallBlock from "./ToolCallBlock.vue"

const runtimeTitle = "\u672c\u8f6e\u8fd0\u884c\u8fc7\u7a0b"
const stageUnit = "\u4e2a\u9636\u6bb5"
const collapseLabel = "\u6536\u8d77"
const expandLabel = "\u5c55\u5f00"
const runningLabel = "\u8fdb\u884c\u4e2d"

const props = defineProps<{
  events: ChatRuntimeEvent[]
}>()

const expanded = ref(false)
const activeEvent = computed(() => props.events[props.events.length - 1] ?? null)

const previewText = computed(() =>
  props.events
    .map((event) => `${statusLabel(event.status)}: ${event.message}`)
    .slice(0, 2)
    .join(" | ")
)

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    thinking: "\u95ee\u9898\u7406\u89e3",
    searching: "\u77e5\u8bc6\u68c0\u7d22",
    reading: "\u8bc1\u636e\u8bfb\u53d6",
    tool_call: "\u5de5\u5177\u8c03\u7528",
    streaming: "\u56de\u7b54\u751f\u6210",
    error: "\u8fd0\u884c\u5931\u8d25",
  }
  return labels[status] || "\u5904\u7406\u4e2d"
}

function statusIcon(status: string) {
  const icons: Record<string, string> = {
    thinking: "\u60f3",
    searching: "\u68c0",
    reading: "\u8bfb",
    tool_call: "\u8c03",
    streaming: "\u7b54",
    error: "\u9519",
  }
  return icons[status] || "\u5904"
}

function isActiveEvent(event: ChatRuntimeEvent) {
  return activeEvent.value?.id === event.id && event.status !== "error"
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "--:--"
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`
}
</script>

<style scoped>
.runtime-shell {
  margin-bottom: 18px;
  border: 1px solid var(--border-color-subtle);
  border-radius: 24px;
  background: color-mix(in srgb, var(--bg-surface) 93%, transparent);
  box-shadow: var(--shadow-sm);
}

.runtime-toggle {
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  padding: 16px 18px;
}

.runtime-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.runtime-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.runtime-live-dots::after {
  content: "";
  display: inline-block;
  width: 14px;
  margin-left: 6px;
  text-align: left;
  animation: runtime-dots 1.4s steps(1, end) infinite;
}

.runtime-count,
.runtime-expand {
  font-size: 13px;
  color: var(--text-tertiary);
}

.runtime-count {
  margin-left: auto;
}

.runtime-preview {
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.runtime-list {
  display: grid;
  gap: 12px;
  padding: 0 18px 18px;
}

.runtime-card {
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.4);
  border: 1px solid transparent;
  transition: transform var(--transition-fast), border-color var(--transition-fast), background-color var(--transition-fast);
}

.runtime-card[data-status="thinking"] {
  border-color: rgba(74, 108, 247, 0.16);
}

.runtime-card[data-status="searching"] {
  border-color: rgba(15, 118, 110, 0.18);
}

.runtime-card[data-status="reading"] {
  border-color: rgba(180, 83, 9, 0.18);
}

.runtime-card[data-status="tool_call"] {
  border-color: rgba(126, 34, 206, 0.18);
}

.runtime-card[data-status="error"] {
  border-color: rgba(217, 45, 32, 0.24);
  background: rgba(255, 244, 243, 0.8);
}

.runtime-card:hover {
  transform: translateY(-1px);
}

.theme-dark .runtime-card[data-status="error"] {
  background: rgba(90, 26, 23, 0.35);
}

.runtime-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.runtime-card-label {
  display: flex;
  align-items: center;
  gap: 10px;
}

.runtime-icon {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary-hover);
  font-size: 12px;
  font-weight: 700;
}

.runtime-card[data-status="searching"] .runtime-icon {
  background: rgba(15, 118, 110, 0.14);
  color: #0f766e;
}

.runtime-card[data-status="reading"] .runtime-icon {
  background: rgba(180, 83, 9, 0.14);
  color: #b45309;
}

.runtime-card[data-status="tool_call"] .runtime-icon {
  background: rgba(126, 34, 206, 0.14);
  color: #7e22ce;
}

.runtime-card[data-status="error"] .runtime-icon {
  background: rgba(217, 45, 32, 0.14);
  color: #b42318;
}

.runtime-card-label strong,
.runtime-time {
  font-size: 13px;
}

.runtime-card-label strong {
  color: var(--text-primary);
}

.runtime-time {
  color: var(--text-tertiary);
}

.runtime-message {
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.65;
}

.runtime-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.runtime-collapse-enter-active,
.runtime-collapse-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.runtime-collapse-enter-from,
.runtime-collapse-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@keyframes runtime-dots {
  0%,
  20% {
    content: "";
  }
  40% {
    content: ".";
  }
  60% {
    content: "..";
  }
  80%,
  100% {
    content: "...";
  }
}
</style>

<template>
  <div v-if="events.length" class="runtime-shell">
    <button class="runtime-toggle" type="button" @click="expanded = !expanded">
      <div class="runtime-head">
        <span class="runtime-title">
          本轮运行过程
          <span v-if="activeEvent" class="runtime-live-dots" aria-hidden="true"></span>
        </span>
        <span class="runtime-count">{{ events.length }} 个阶段</span>
        <span class="runtime-expand">{{ expanded ? "收起" : "展开" }}</span>
      </div>
      <p v-if="!expanded" class="runtime-preview">{{ previewText }}</p>
    </button>

    <transition name="runtime-collapse">
      <div v-if="expanded" class="runtime-list">
      <article
        v-for="event in events"
        :key="event.id"
        class="runtime-card"
        :data-status="event.status"
      >
        <div class="runtime-card-head">
          <div class="runtime-card-label">
            <span class="runtime-icon">{{ statusIcon(event.status) }}</span>
            <strong>{{ statusLabel(event.status) }}</strong>
          </div>
          <span class="runtime-time">
            {{ isActiveEvent(event) ? "进行中" : formatTime(event.timestamp) }}
          </span>
        </div>
        <p class="runtime-message">{{ event.message }}</p>
      </article>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import type { ChatRuntimeEvent } from "@/stores/chat"

const props = defineProps<{
  events: ChatRuntimeEvent[]
}>()

const expanded = ref(false)

const activeEvent = computed(() => props.events[props.events.length - 1] ?? null)

const previewText = computed(() =>
  props.events
    .map((event) => `${statusLabel(event.status)}: ${event.message}`)
    .slice(0, 2)
    .join(" · ")
)

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    thinking: "问题理解",
    searching: "知识检索",
    reading: "证据读取",
    tool_call: "工具调用",
    streaming: "回答生成",
    error: "运行失败",
  }
  return labels[status] || "处理中"
}

function statusIcon(status: string) {
  const icons: Record<string, string> = {
    thinking: "思",
    searching: "检",
    reading: "读",
    tool_call: "调",
    streaming: "答",
    error: "错",
  }
  return icons[status] || "态"
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

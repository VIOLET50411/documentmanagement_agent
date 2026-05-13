<template>
  <div class="status-message" :data-tone="tone">
    <div class="status-head" :class="{ compact: !title && !dismissible }">
      <strong v-if="title" class="status-title">{{ title }}</strong>
      <button v-if="dismissible" class="status-dismiss" type="button" aria-label="关闭提示" @click="$emit('dismiss')">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
    <div class="status-body">
      <slot>{{ message }}</slot>
    </div>
    <button v-if="actionLabel" class="status-action" type="button" @click="$emit('action')">{{ actionLabel }}</button>
  </div>
</template>

<script setup lang="ts">
defineEmits<{
  (event: "dismiss"): void
  (event: "action"): void
}>()

withDefaults(
  defineProps<{
    message?: string
    title?: string
    tone?: "error" | "info" | "success"
    dismissible?: boolean
    actionLabel?: string
  }>(),
  {
    message: "",
    title: "",
    tone: "info",
    dismissible: false,
    actionLabel: "",
  },
)
</script>

<style scoped>
.status-message {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(107, 114, 128, 0.18);
  background: rgba(107, 114, 128, 0.08);
  color: #4b5563;
}

.status-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.status-head.compact {
  margin-bottom: 0;
}

.status-title {
  display: block;
  margin-bottom: 4px;
  color: inherit;
}

.status-body {
  line-height: 1.6;
}

.status-dismiss,
.status-action {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.status-dismiss {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  opacity: 0.72;
  border-radius: 999px;
}

.status-dismiss svg {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  stroke-width: 2;
  fill: none;
  stroke-linecap: round;
}

.status-dismiss:hover {
  background: rgba(0, 0, 0, 0.06);
  opacity: 1;
}

.status-action {
  margin-top: 10px;
  padding: 0;
  font-size: 13px;
  font-weight: 600;
}

.status-message[data-tone="error"] {
  border-color: rgba(214, 69, 65, 0.18);
  background: rgba(214, 69, 65, 0.08);
  color: #b3261e;
}

.status-message[data-tone="success"] {
  border-color: rgba(24, 121, 78, 0.18);
  background: rgba(24, 121, 78, 0.08);
  color: #18794e;
}
</style>

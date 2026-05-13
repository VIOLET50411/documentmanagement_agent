<template>
  <div class="empty-state">
    <div class="empty-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h11A2.5 2.5 0 0 1 20 7.5v9A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z" />
        <path d="M8 10h8M8 14h5" />
      </svg>
    </div>
    <div class="empty-copy">
      <p class="empty-title">{{ title }}</p>
      <p v-if="description" class="empty-description">{{ description }}</p>
    </div>
    <button v-if="actionLabel" class="empty-action" type="button" @click="$emit('action')">{{ actionLabel }}</button>
  </div>
</template>

<script setup lang="ts">
defineEmits<{
  (event: "action"): void
}>()

withDefaults(
  defineProps<{
    title: string
    description?: string
    actionLabel?: string
  }>(),
  {
    description: "",
    actionLabel: "",
  },
)
</script>

<style scoped>
.empty-state {
  display: grid;
  gap: 10px;
  padding: 18px;
  border-radius: 12px;
  border: 1px dashed var(--border-color);
  background: color-mix(in srgb, var(--bg-surface-hover) 72%, transparent);
  color: var(--text-secondary);
}

.empty-icon {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(79, 124, 255, 0.08);
  color: var(--color-primary);
}

.empty-icon svg {
  width: 18px;
  height: 18px;
  stroke: currentColor;
  stroke-width: 1.8;
  fill: none;
  stroke-linecap: round;
}

.empty-title {
  margin: 0;
  color: var(--text-primary);
  font-weight: 600;
}

.empty-description {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.empty-action {
  justify-self: start;
  margin-top: 2px;
  border: 0;
  background: transparent;
  color: var(--color-primary-hover);
  font-size: 13px;
  font-weight: 600;
  padding: 0;
  cursor: pointer;
}
</style>

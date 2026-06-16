<template>
  <div class="empty-state animate-fade-in">
    <div class="empty-icon" aria-hidden="true">
      <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
        <!-- Minimalist sophisticated illustration -->
        <circle cx="60" cy="60" r="50" fill="var(--bg-surface-strong)" opacity="0.4" />
        <path d="M40 50h40v30H40z" fill="none" stroke="var(--border-color-strong)" stroke-width="2" stroke-linejoin="round" stroke-dasharray="4 4" />
        <path d="M50 45h20v5H50z" fill="var(--color-primary)" opacity="0.1" />
        <path d="M50 45h20" fill="none" stroke="var(--color-primary)" stroke-width="2" stroke-linecap="round" />
        <path d="M45 60h30M45 70h20" fill="none" stroke="var(--border-color-strong)" stroke-width="2" stroke-linecap="round" />
        <circle cx="75" cy="75" r="12" fill="var(--bg-surface)" stroke="var(--color-primary)" stroke-width="2" />
        <path d="M83 83l10 10" fill="none" stroke="var(--color-primary)" stroke-width="2" stroke-linecap="round" />
      </svg>
    </div>
    <div class="empty-copy">
      <h3 class="empty-title">{{ title }}</h3>
      <p v-if="description" class="empty-description">{{ description }}</p>
    </div>
    <button v-if="actionLabel" class="btn btn-secondary btn-sm empty-action" type="button" @click="$emit('action')">
      {{ actionLabel }}
    </button>
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
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 48px 24px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--bg-surface-hover) 40%, transparent);
  border: 1px dashed var(--border-color-subtle);
  backdrop-filter: blur(8px);
}

.empty-icon {
  width: 120px;
  height: 120px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-icon svg {
  width: 100%;
  height: 100%;
}

.empty-title {
  margin: 0 0 8px;
  color: var(--text-primary);
  font-size: 1.1rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.empty-description {
  margin: 0;
  font-size: 0.95rem;
  color: var(--text-tertiary);
  line-height: 1.6;
  max-width: 400px;
}

.empty-action {
  margin-top: 24px;
  transition: transform 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.empty-action:hover {
  transform: translateY(-1px);
}
</style>

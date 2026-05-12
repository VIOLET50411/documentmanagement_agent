<template>
  <div class="chat-composer-wrapper" :class="{ compact }">
    <div class="chat-composer">
      <textarea
        ref="textareaRef"
        :value="modelValue"
        class="hero-input"
        :placeholder="placeholder"
        rows="1"
        :disabled="disabled"
        @input="handleInput"
        @keydown.enter.exact.prevent="$emit('submit')"
      ></textarea>

      <div class="composer-bottom">
        <div class="composer-tools">
          <button class="tool-btn" type="button" :title="focusLabel" @click="focusTextarea">
            <span class="icon">⌕</span>
          </button>
        </div>
        <div class="composer-actions">
          <label class="model-selector">
            <span class="sr-only">{{ modelSelectorLabel }}</span>
            <select
              :value="selectedModel"
              class="model-select"
              @change="$emit('update:selectedModel', ($event.target as HTMLSelectElement).value)"
            >
              <option value="qwen2.5:1.5b">DocMind Smart 1.0 (1.5B)</option>
              <option value="qwen2.5:7b">DocMind Smart 1.0 (7B)</option>
            </select>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from "vue"

const focusLabel = "\u805a\u7126\u8f93\u5165\u6846"
const modelSelectorLabel = "\u9009\u62e9\u6a21\u578b"

const props = defineProps<{
  modelValue: string
  selectedModel: string
  placeholder: string
  disabled?: boolean
  compact?: boolean
}>()

const emit = defineEmits<{
  "update:modelValue": [value: string]
  "update:selectedModel": [value: string]
  submit: []
}>()

const textareaRef = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.modelValue,
  async () => {
    await nextTick()
    resizeTextarea()
  },
  { immediate: true }
)

function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  emit("update:modelValue", target.value)
  resizeTextarea()
}

function resizeTextarea() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = "auto"
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function focusTextarea() {
  textareaRef.value?.focus()
}
</script>

<style scoped>
.chat-composer-wrapper {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
}

.chat-composer {
  width: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
  padding: 16px 20px;
  transition: box-shadow var(--transition-fast), border-color var(--transition-fast);
}

.chat-composer:focus-within {
  border-color: var(--border-color-strong);
  box-shadow: var(--shadow-lg);
}

.hero-input {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  min-height: 48px;
  background: transparent;
  color: var(--text-primary);
  font-size: 1.05rem;
  line-height: 1.5;
  padding: 0;
}

.hero-input::placeholder {
  color: var(--text-tertiary);
}

.composer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}

.composer-tools,
.composer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 0;
  background: transparent;
  display: grid;
  place-items: center;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.tool-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}

.icon {
  font-size: 18px;
  line-height: 1;
}

.model-select {
  border: 0;
  background: transparent;
  padding: 6px 8px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  appearance: none;
  font-weight: 500;
  transition: color var(--transition-fast);
}

.model-select:hover {
  color: var(--text-primary);
}
</style>

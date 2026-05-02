<template>
  <div class="chat-composer" :class="{ compact }">
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
        <button class="composer-plus" type="button" @click="focusTextarea">+</button>
        <label class="model-selector">
          <span class="sr-only">选择模型</span>
          <select
            :value="selectedModel"
            class="model-select"
            @change="$emit('update:selectedModel', ($event.target as HTMLSelectElement).value)"
          >
            <option value="docmind-smart">标准问答</option>
            <option value="docmind-retrieval">检索增强</option>
            <option value="docmind-brief">精简速答</option>
          </select>
        </label>
      </div>
      <button class="btn btn-primary" type="button" :disabled="disabled || !modelValue.trim()" @click="$emit('submit')">
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from "vue"

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
.chat-composer {
  padding: 20px;
}

.chat-composer.compact {
  padding: 16px 18px;
}

.hero-input {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  min-height: 88px;
  background: transparent;
  color: var(--text-primary);
  font-size: 1.05rem;
  line-height: 1.7;
}

.compact .hero-input {
  min-height: 58px;
}

.hero-input::placeholder {
  color: var(--text-tertiary);
}

.composer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.composer-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}

.composer-plus {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.36);
}

.model-select {
  min-width: 160px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.36);
  padding: 10px 14px;
  color: var(--text-primary);
}

@media (max-width: 640px) {
  .composer-bottom {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>

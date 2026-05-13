<template>
  <div v-if="event.degraded && event.fallbackReason" class="fallback-notice">
    <strong>{{ title }}</strong>
    <span>{{ fallbackReasonLabel(event.fallbackReason) }}</span>
  </div>
</template>

<script setup lang="ts">
import type { ChatRuntimeEvent } from "@/stores/chat"

const title = "已触发降级路径"

defineProps<{
  event: ChatRuntimeEvent
}>()

function fallbackReasonLabel(reason: string) {
  const labels: Record<string, string> = {
    partial_backend_failure: "部分后端暂时不可用，系统已切换到降级处理。",
    retrieval_timeout: "检索超时，系统改用较保守的回答路径。",
    retrieval_unavailable: "检索服务暂时不可用，系统改用降级回答。",
    vector_search_failed: "向量检索失败，系统已回退到替代路径。",
    keyword_search_failed: "关键词检索失败，系统已回退到替代路径。",
    citation_generation_failed: "引用生成失败，当前回答可能不会附带完整出处。",
    tool_unavailable: "所需工具暂时不可用，系统已继续执行其余步骤。",
    tool_timeout: "工具调用超时，系统已跳过该步骤继续处理。",
    model_unavailable: "当前模型暂时不可用，系统已切换到备用路径。",
    upstream_unavailable: "上游服务暂时不可用，系统已自动降级。",
  }
  return labels[reason] || `已触发降级处理：${reason}`
}
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

<template>
  <div class="content-block">
    <div class="block-head">
      <div>
        <h2>通知记录</h2>
        <p>查看最近的推送记录和文档处理事件。</p>
      </div>
      <button class="btn btn-ghost btn-sm" @click="loadEvents" :disabled="loadingEvents">
        {{ loadingEvents ? "刷新中..." : "刷新" }}
      </button>
    </div>

    <section class="settings-panel">
      <ul v-if="events.length" class="event-list">
        <li v-for="(event, index) in events" :key="`${event.document_id || 'evt'}-${index}`" class="event-item">
          <div class="event-topline">
            <strong>{{ event.title || "推送事件" }}</strong>
            <span class="badge badge-primary">{{ event.status || "-" }}</span>
          </div>
          <p class="event-body">{{ event.body || "-" }}</p>
          <p class="event-meta">
            <span>文档：{{ event.document_id || "-" }}</span>
            <span>时间：{{ formatDate(event.timestamp) }}</span>
            <span>设备数：{{ event.devices?.length || 0 }}</span>
          </p>
        </li>
      </ul>
      <EmptyState v-else title="最近没有推送事件。" description="文档处理或通知下发后，这里会显示最近的事件记录。" />
    </section>
  </div>
</template>

<script setup lang="ts">
import EmptyState from "@/components/common/EmptyState.vue"

defineProps<{
  events: Array<Record<string, any>>
  loadingEvents: boolean
  formatDate: (value?: string | null) => string
  loadEvents: () => Promise<void>
}>()
</script>

<style scoped>
.content-block {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.block-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.block-head h2 {
  font-size: 1.25rem;
  font-weight: 600;
}

.block-head p,
.event-body,
.event-meta,
.empty-text {
  color: var(--text-secondary);
}

.settings-panel {
  border: none;
  background: transparent;
  padding: 0;
  box-shadow: none;
  backdrop-filter: none;
  border-radius: 0;
  margin-bottom: 32px;
}

.settings-panel h3 {
  font-size: 0.95rem;
  font-weight: 600;
  margin-bottom: 16px;
}

.event-list {
  display: grid;
  gap: 12px;
}

.event-item {
  list-style: none;
  padding: 16px 18px;
  border-radius: 22px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface-hover);
}

.event-topline {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.event-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
  font-size: var(--text-sm);
}

@media (max-width: 640px) {
  .block-head {
    flex-direction: column;
  }
}
</style>




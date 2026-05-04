<template>
  <div class="content-block">
    <div class="block-head">
      <div>
        <h2>设备</h2>
      </div>
      <button class="btn btn-ghost btn-sm" @click="loadPushData" :disabled="loadingDevices || loadingEvents || loadingSummary">
        {{ loadingDevices || loadingEvents || loadingSummary ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <section class="settings-panel">
      <h3>当前设备同步状态</h3>
      <div class="status-grid">
        <div class="status-card">
          <span>运行环境</span>
          <strong>{{ isNativeRuntime ? nativePlatformLabel : 'Web 浏览器' }}</strong>
          <small>{{ isNativeRuntime ? '支持自动注册与心跳续期' : '仅支持手动登记推送设备' }}</small>
        </div>
        <div class="status-card">
          <span>本地记录</span>
          <strong>{{ storedPushRegistration ? '已保存' : '未保存' }}</strong>
          <small>{{ storedPushRegistration ? maskToken(storedPushRegistration.token) : '当前设备尚未保存本地 token' }}</small>
        </div>
        <div class="status-card">
          <span>后端状态</span>
          <strong>{{ currentTokenStatusLabel }}</strong>
          <small>{{ currentTokenStatusDetail }}</small>
        </div>
      </div>

      <div class="summary-strip" v-if="deviceSummary">
        <span class="summary-pill">总设备 {{ deviceSummary.total }}</span>
        <span class="summary-pill success">启用 {{ deviceSummary.active }}</span>
        <span class="summary-pill muted">停用 {{ deviceSummary.inactive }}</span>
        <span v-for="(stats, platform) in deviceSummary.by_platform" :key="platform" class="summary-pill platform">
          {{ platform }} {{ stats.active }}/{{ stats.total }}
        </span>
      </div>
    </section>

    <section class="settings-panel">
      <h3>当前设备推送注册</h3>
      <p class="panel-copy">原生 App 内点击下方按钮，会向系统申请真实设备 token 并自动同步到后端。</p>
      <div class="device-actions">
        <button class="btn btn-primary" :disabled="registeringNativePush" @click="registerCurrentDevicePush">
          {{ registeringNativePush ? '注册中...' : '自动注册当前设备' }}
        </button>
        <button class="btn btn-ghost" :disabled="heartbeatingNativePush || !storedPushRegistration" @click="heartbeatCurrentDevicePush">
          {{ heartbeatingNativePush ? '续期中...' : '发送一次心跳' }}
        </button>
        <button class="btn btn-ghost" :disabled="registeringNativePush || !storedPushRegistration || deviceSummary?.current_token_status !== 'matched_inactive'" @click="registerCurrentDevicePush">
          重新绑定当前设备
        </button>
        <span class="helper-text">
          {{ isNativeRuntime ? `当前运行环境：${nativePlatformLabel}` : '当前不是原生 App 环境，自动注册不可用。' }}
        </span>
      </div>
      <p v-if="nativePushMessage" class="feedback-message">{{ nativePushMessage }}</p>
    </section>

    <section class="settings-panel">
      <h3>手动登记设备</h3>
      <form class="device-form" @submit.prevent="registerDevice">
        <label class="field">
          <span>平台</span>
          <select v-model="deviceForm.platform" class="input">
            <option value="android">Android</option>
            <option value="web">Web</option>
            <option value="wechat">微信小程序</option>
          </select>
        </label>

        <label class="field">
          <span>设备名称</span>
          <input v-model="deviceForm.device_name" class="input" type="text" placeholder="例如 Pixel 8 / iPhone 15 / Chrome" />
        </label>

        <label class="field span-2">
          <span>设备 Token</span>
          <textarea v-model="deviceForm.device_token" class="input large-input" rows="3" placeholder="请输入移动端、WebPush 或小程序的真实设备 token"></textarea>
        </label>

        <label class="field">
          <span>App 版本</span>
          <input v-model="deviceForm.app_version" class="input" type="text" placeholder="例如 1.0.0" />
        </label>

        <div class="field actions">
          <span></span>
          <button class="btn btn-primary" type="submit" :disabled="registering">
            {{ registering ? '登记中...' : '登记设备' }}
          </button>
        </div>
      </form>

      <p v-if="deviceMessage" class="feedback-message">{{ deviceMessage }}</p>
    </section>

    <section class="settings-panel">
      <h3>已登记设备</h3>
      <table v-if="devices.length" class="data-table">
        <thead>
          <tr>
            <th>平台</th>
            <th>设备</th>
            <th>版本</th>
            <th>Token</th>
            <th>状态</th>
            <th>最近活跃</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="device in devices" :key="device.id">
            <td>{{ device.platform }}</td>
            <td>{{ device.device_name || '-' }}</td>
            <td>{{ device.app_version || '-' }}</td>
            <td class="token-cell">{{ maskToken(device.device_token) }}</td>
            <td>
              <span class="badge" :class="device.is_active ? 'badge-success' : 'badge-muted'">
                {{ device.is_active ? '已启用' : '已停用' }}
              </span>
            </td>
            <td>{{ formatDate(device.last_seen_at || device.updated_at) }}</td>
            <td>
              <button class="btn btn-ghost btn-sm" :disabled="unregisteringToken === device.device_token" @click="unregisterDevice(device)">
                {{ unregisteringToken === device.device_token ? '注销中...' : '注销' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">当前还没有登记过推送设备。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  isNativeRuntime: boolean
  nativePlatformLabel: string
  devices: Array<Record<string, any>>
  deviceSummary: Record<string, any> | null
  storedPushRegistration: Record<string, any> | null
  deviceForm: Record<string, any>
  loadingDevices: boolean
  loadingEvents: boolean
  loadingSummary: boolean
  registering: boolean
  unregisteringToken: string
  registeringNativePush: boolean
  heartbeatingNativePush: boolean
  deviceMessage: string
  nativePushMessage: string
  currentTokenStatusLabel: string
  currentTokenStatusDetail: string
  formatDate: (value?: string | null) => string
  maskToken: (token?: string) => string
  loadPushData: () => Promise<void>
  registerCurrentDevicePush: () => Promise<void>
  heartbeatCurrentDevicePush: () => Promise<void>
  registerDevice: () => Promise<void>
  unregisterDevice: (device: any) => Promise<void>
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

.status-grid,
.device-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field span {
  color: var(--text-secondary);
  font-size: 0.95rem;
}

.span-2 {
  grid-column: span 2;
}

.large-input {
  min-height: 118px;
  resize: vertical;
}

.status-card {
  border-radius: 22px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface-hover);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-card span,
.status-card small,
.panel-copy,
.helper-text {
  color: var(--text-secondary);
}

.status-card strong {
  font-size: 1.06rem;
}

.summary-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

.summary-pill {
  border-radius: 999px;
  padding: 8px 12px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.summary-pill.success {
  color: var(--color-success);
}

.summary-pill.muted {
  color: var(--text-tertiary);
}

.summary-pill.platform {
  color: var(--text-primary);
}

.device-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.actions {
  justify-content: flex-end;
}

.feedback-message {
  margin-top: 18px;
  color: var(--color-primary-hover);
  font-weight: 600;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 12px 10px;
  border-bottom: 1px solid var(--border-color-subtle);
  text-align: left;
  vertical-align: top;
}

.data-table th {
  font-size: 0.76rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
}

.token-cell {
  font-family: var(--font-mono);
  font-size: 0.82rem;
}

@media (max-width: 1120px) {
  .status-grid,
  .device-form {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: span 1;
  }
}

@media (max-width: 640px) {
  .block-head {
    flex-direction: column;
  }
}
</style>

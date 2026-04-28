<template>
  <div class="settings-page">
    <header class="settings-header">
      <div>
        <p class="settings-eyebrow">工作台设置</p>
        <h1>设置</h1>
      </div>
      <p class="settings-summary">统一管理账户、外观、回答偏好、设备与通知。</p>
    </header>

    <div class="settings-shell">
      <aside class="settings-nav">
        <div class="settings-nav-card">
          <button
            v-for="item in sections"
            :key="item.key"
            class="settings-tab"
            :class="{ active: activeSection === item.key }"
            @click="setSection(item.key)"
          >
            <span class="settings-tab-title">{{ item.label }}</span>
            <small>{{ item.description }}</small>
          </button>
        </div>
      </aside>

      <section class="settings-content">
        <div v-if="activeSection === 'general'" class="content-block">
          <div class="block-head">
            <div>
              <h2>通用</h2>
              <p>控制外观、提示方式和个人资料展示。</p>
            </div>
          </div>

          <div class="panel-grid">
            <section class="settings-panel">
              <h3>基础资料</h3>
              <div class="form-grid">
                <label class="field">
                  <span>用户名</span>
                  <input class="input" :value="user?.username || ''" readonly />
                </label>
                <label class="field">
                  <span>显示名称</span>
                  <input class="input" :value="user?.username || ''" readonly />
                </label>
              </div>
              <label class="field">
                <span>部门</span>
                <input class="input" :value="user?.department || '未设置'" readonly />
              </label>
            </section>

            <section class="settings-panel">
              <h3>外观模式</h3>
              <div class="theme-cards">
                <button class="theme-card" :class="{ active: !themeStore.isDark }" @click="themeStore.setTheme('light')">
                  <span class="theme-preview theme-light"></span>
                  <strong>浅色模式</strong>
                  <small>适合日间浏览和长时间阅读</small>
                </button>
                <button class="theme-card" :class="{ active: themeStore.isDark }" @click="themeStore.setTheme('dark')">
                  <span class="theme-preview theme-dark-preview"></span>
                  <strong>深色模式</strong>
                  <small>低照环境下更稳定，界面对比更克制</small>
                </button>
              </div>
            </section>
          </div>

          <section class="settings-panel">
            <h3>提示与通知</h3>
            <div class="toggle-list">
              <div class="toggle-item">
                <div>
                  <strong>处理完成通知</strong>
                  <p>文档入库、索引重建或批处理结束后给出提醒。</p>
                </div>
                <button class="toggle-switch" :class="{ on: notificationsEnabled }" @click="notificationsEnabled = !notificationsEnabled">
                  <span></span>
                </button>
              </div>
              <div class="toggle-item">
                <div>
                  <strong>侧边状态提示</strong>
                  <p>对话阶段变化时，在顶部显示简短状态反馈。</p>
                </div>
                <button class="toggle-switch" :class="{ on: statusHintsEnabled }" @click="statusHintsEnabled = !statusHintsEnabled">
                  <span></span>
                </button>
              </div>
            </div>
          </section>
        </div>

        <div v-else-if="activeSection === 'account'" class="content-block">
          <div class="block-head">
            <div>
              <h2>账户</h2>
              <p>查看当前登录身份、租户信息和邮箱状态。</p>
            </div>
          </div>

          <section class="settings-panel">
            <div class="info-list">
              <div class="info-row"><span>用户名</span><strong>{{ user?.username || '-' }}</strong></div>
              <div class="info-row"><span>角色</span><strong>{{ roleLabel(user?.role) }}</strong></div>
              <div class="info-row"><span>邮箱</span><strong>{{ user?.email || '-' }}</strong></div>
              <div class="info-row"><span>邮箱状态</span><strong>{{ user?.email_verified ? '已验证' : '未验证' }}</strong></div>
              <div class="info-row"><span>租户</span><strong>{{ user?.tenant_id || '-' }}</strong></div>
            </div>
          </section>
        </div>

        <div v-else-if="activeSection === 'preferences'" class="content-block">
          <div class="block-head">
            <div>
              <h2>回答偏好</h2>
              <p>定义默认输出风格、语言和引用偏好。</p>
            </div>
          </div>

          <section class="settings-panel">
            <div class="form-grid">
              <label class="field">
                <span>回答风格</span>
                <select class="input" v-model="responseStyle">
                  <option value="direct">简洁直接</option>
                  <option value="detailed">详细完整</option>
                  <option value="bullets">要点列表</option>
                </select>
              </label>

              <label class="field">
                <span>默认语言</span>
                <select class="input" v-model="responseLanguage">
                  <option value="zh-CN">中文</option>
                  <option value="en-US">English</option>
                </select>
              </label>
            </div>

            <label class="field">
              <span>默认回答要求</span>
              <textarea class="input large-input" readonly>优先给出结论、引用来源和下一步建议；信息不足时明确说明限制。</textarea>
            </label>
          </section>
        </div>

        <div v-else-if="activeSection === 'devices'" class="content-block">
          <div class="block-head">
            <div>
              <h2>设备</h2>
              <p>登记推送设备，用于后续 App、移动端或 Web 提醒。</p>
            </div>
            <button class="btn btn-ghost btn-sm" @click="loadPushData" :disabled="loadingDevices || loadingEvents">
              {{ loadingDevices || loadingEvents ? '刷新中…' : '刷新' }}
            </button>
          </div>

          <section class="settings-panel">
            <form class="device-form" @submit.prevent="registerDevice">
              <label class="field">
                <span>平台</span>
                <select v-model="deviceForm.platform" class="input">
                  <option value="android">Android</option>
                  <option value="ios">iOS</option>
                  <option value="web">Web</option>
                </select>
              </label>

              <label class="field">
                <span>设备名称</span>
                <input v-model="deviceForm.device_name" class="input" type="text" placeholder="例如 Pixel 8 / iPhone 15" />
              </label>

              <label class="field span-2">
                <span>设备 Token</span>
                <textarea v-model="deviceForm.device_token" class="input large-input" rows="3" placeholder="请输入移动推送 token"></textarea>
              </label>

              <label class="field">
                <span>App 版本</span>
                <input v-model="deviceForm.app_version" class="input" type="text" placeholder="例如 1.0.0" />
              </label>

              <div class="field actions">
                <span></span>
                <button class="btn btn-primary" type="submit" :disabled="registering">
                  {{ registering ? '登记中…' : '登记设备' }}
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
                  <td>{{ device.is_active ? '已启用' : '已停用' }}</td>
                  <td>{{ formatDate(device.last_seen_at || device.updated_at) }}</td>
                  <td>
                    <button class="btn btn-ghost btn-sm" :disabled="unregisteringToken === device.device_token" @click="unregisterDevice(device)">
                      {{ unregisteringToken === device.device_token ? '注销中…' : '注销' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else class="empty-text">当前还没有登记推送设备。</p>
          </section>
        </div>

        <div v-else class="content-block">
          <div class="block-head">
            <div>
              <h2>通知</h2>
              <p>查看最近的推送记录和文档处理事件。</p>
            </div>
            <button class="btn btn-ghost btn-sm" @click="loadEvents" :disabled="loadingEvents">
              {{ loadingEvents ? '刷新中…' : '刷新' }}
            </button>
          </div>

          <section class="settings-panel">
            <ul v-if="events.length" class="event-list">
              <li v-for="(event, index) in events" :key="`${event.document_id || 'evt'}-${index}`" class="event-item">
                <div class="event-topline">
                  <strong>{{ event.title || '推送事件' }}</strong>
                  <span class="badge badge-primary">{{ event.status || '-' }}</span>
                </div>
                <p class="event-body">{{ event.body || '-' }}</p>
                <p class="event-meta">
                  <span>文档：{{ event.document_id || '-' }}</span>
                  <span>时间：{{ formatDate(event.timestamp) }}</span>
                  <span>设备数：{{ event.devices?.length || 0 }}</span>
                </p>
              </li>
            </ul>
            <p v-else class="empty-text">最近没有推送事件。</p>
          </section>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { notificationsApi, type PushDevicePayload } from '@/api/notifications'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

type PushDeviceRecord = PushDevicePayload & {
  id: string
  tenant_id: string
  user_id: string
  is_active: boolean
  created_at?: string
  updated_at?: string
  last_seen_at?: string
}

type PushEventRecord = {
  document_id?: string
  title?: string
  body?: string
  status?: string
  timestamp?: string
  devices?: Array<Record<string, unknown>>
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()
const user = computed(() => authStore.user)

const sections = [
  { key: 'general', label: '通用', description: '外观、资料与提示' },
  { key: 'account', label: '账户', description: '身份、角色与租户' },
  { key: 'preferences', label: '偏好', description: '回答风格与语言' },
  { key: 'devices', label: '设备', description: '推送登记与状态' },
  { key: 'events', label: '通知', description: '最近推送事件' },
]

const activeSection = ref('general')
const responseStyle = ref('direct')
const responseLanguage = ref('zh-CN')
const notificationsEnabled = ref(true)
const statusHintsEnabled = ref(true)

const deviceForm = reactive<PushDevicePayload>({
  platform: 'android',
  device_token: '',
  device_name: '',
  app_version: '',
})

const devices = ref<PushDeviceRecord[]>([])
const events = ref<PushEventRecord[]>([])
const loadingDevices = ref(false)
const loadingEvents = ref(false)
const registering = ref(false)
const unregisteringToken = ref('')
const deviceMessage = ref('')

watch(
  () => route.query.section,
  (section) => {
    if (typeof section === 'string' && sections.some((item) => item.key === section)) {
      activeSection.value = section
    }
  },
  { immediate: true }
)

function setSection(section: string) {
  activeSection.value = section
  router.replace({ query: { ...route.query, section } })
}

function roleLabel(role?: string) {
  const map: Record<string, string> = { ADMIN: '管理员', MANAGER: '经理', EMPLOYEE: '员工', VIEWER: '访客' }
  return role ? map[role] || role : '-'
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function maskToken(token?: string) {
  if (!token) return '-'
  if (token.length <= 12) return token
  return `${token.slice(0, 6)}...${token.slice(-6)}`
}

async function loadDevices() {
  loadingDevices.value = true
  try {
    devices.value = await notificationsApi.listDevices()
  } finally {
    loadingDevices.value = false
  }
}

async function loadEvents() {
  loadingEvents.value = true
  try {
    const response = await notificationsApi.listEvents(20)
    events.value = response?.items || []
  } finally {
    loadingEvents.value = false
  }
}

async function loadPushData() {
  await Promise.all([loadDevices(), loadEvents()])
}

async function registerDevice() {
  if (!deviceForm.device_token.trim()) {
    deviceMessage.value = '请先填写设备 token。'
    return
  }
  registering.value = true
  deviceMessage.value = ''
  try {
    await notificationsApi.registerDevice({
      platform: deviceForm.platform,
      device_token: deviceForm.device_token.trim(),
      device_name: deviceForm.device_name?.trim() || undefined,
      app_version: deviceForm.app_version?.trim() || undefined,
    })
    deviceMessage.value = '设备登记成功。'
    deviceForm.device_token = ''
    deviceForm.device_name = ''
    deviceForm.app_version = ''
    await loadPushData()
  } catch (error: any) {
    deviceMessage.value = error?.response?.data?.detail || '设备登记失败，请重试。'
  } finally {
    registering.value = false
  }
}

async function unregisterDevice(device: PushDeviceRecord) {
  unregisteringToken.value = device.device_token
  deviceMessage.value = ''
  try {
    await notificationsApi.unregisterDevice({
      platform: device.platform,
      device_token: device.device_token,
    })
    deviceMessage.value = '设备已注销。'
    await loadPushData()
  } catch (error: any) {
    deviceMessage.value = error?.response?.data?.detail || '设备注销失败，请重试。'
  } finally {
    unregisteringToken.value = ''
  }
}

onMounted(loadPushData)
</script>

<style scoped>
.settings-page {
  height: 100%;
  overflow-y: auto;
  padding: 6px 22px 28px;
}

.settings-header,
.settings-shell {
  max-width: 1440px;
  margin: 0 auto;
}

.settings-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 24px;
  padding: 18px 0 24px;
}

.settings-eyebrow {
  color: var(--text-tertiary);
  font-size: 0.86rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 10px;
}

.settings-header h1 {
  font-family: var(--font-serif);
  font-size: 3rem;
  letter-spacing: -0.03em;
}

.settings-summary {
  max-width: 360px;
  color: var(--text-secondary);
  text-align: right;
}

.settings-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 42px;
  align-items: start;
}

.settings-nav {
  position: sticky;
  top: 18px;
}

.settings-nav-card {
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 28px;
  background: color-mix(in srgb, var(--bg-surface) 92%, transparent);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(18px);
}

.settings-tab {
  width: 100%;
  border: none;
  background: transparent;
  border-radius: 18px;
  padding: 14px 16px;
  text-align: left;
  color: var(--text-primary);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.settings-tab + .settings-tab {
  margin-top: 6px;
}

.settings-tab small {
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.settings-tab:hover,
.settings-tab.active {
  background: var(--bg-surface-hover);
}

.settings-tab.active {
  box-shadow: inset 0 0 0 1px var(--border-color);
}

.settings-tab-title {
  font-size: 0.98rem;
  font-weight: 600;
}

.settings-content {
  min-width: 0;
}

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
  font-size: 2rem;
  letter-spacing: -0.02em;
}

.block-head p,
.empty-text,
.event-body,
.event-meta {
  color: var(--text-secondary);
}

.panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.settings-panel {
  border: 1px solid var(--border-color);
  border-radius: 30px;
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent);
  padding: 24px;
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(18px);
}

.settings-panel h3 {
  font-size: 1.1rem;
  margin-bottom: 18px;
}

.form-grid,
.device-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
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

.large-input {
  min-height: 118px;
  resize: vertical;
}

.theme-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.theme-card {
  border: 1px solid var(--border-color);
  border-radius: 24px;
  background: transparent;
  padding: 14px;
  text-align: left;
  color: var(--text-primary);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: transform var(--transition-fast), border-color var(--transition-fast), background-color var(--transition-fast);
}

.theme-card:hover,
.theme-card.active {
  border-color: var(--border-color-strong);
  background: var(--bg-surface-hover);
  transform: translateY(-1px);
}

.theme-preview {
  display: block;
  width: 100%;
  height: 110px;
  border-radius: 18px;
  border: 1px solid var(--border-color);
}

.theme-light {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(244, 240, 234, 0.95)),
    linear-gradient(90deg, rgba(217, 203, 184, 0.45) 0 28%, rgba(255, 255, 255, 0) 28%);
}

.theme-dark-preview {
  background:
    linear-gradient(180deg, rgba(33, 29, 24, 0.98), rgba(23, 19, 15, 0.98)),
    linear-gradient(90deg, rgba(78, 67, 54, 0.78) 0 28%, rgba(255, 255, 255, 0) 28%);
}

.toggle-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.toggle-item {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border-color-subtle);
}

.toggle-item:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.toggle-item strong {
  display: block;
  font-size: 1rem;
}

.toggle-item p {
  color: var(--text-secondary);
  margin-top: 6px;
}

.toggle-switch {
  width: 52px;
  height: 30px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: rgba(61, 56, 51, 0.08);
  padding: 2px;
  cursor: pointer;
}

.toggle-switch span {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #fff;
  display: block;
  transition: transform var(--transition-fast);
}

.toggle-switch.on {
  background: var(--color-primary);
}

.toggle-switch.on span {
  transform: translateX(22px);
}

.info-list {
  display: grid;
  gap: 14px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-color-subtle);
}

.info-row span {
  color: var(--text-secondary);
}

.span-2 {
  grid-column: span 2;
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

@media (max-width: 1120px) {
  .panel-grid,
  .theme-cards {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 980px) {
  .settings-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .settings-summary {
    text-align: left;
  }

  .settings-shell {
    grid-template-columns: 1fr;
    gap: 28px;
  }

  .settings-nav {
    position: static;
  }

  .settings-nav-card {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .settings-tab + .settings-tab {
    margin-top: 0;
  }

  .form-grid,
  .device-form {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: span 1;
  }
}

@media (max-width: 640px) {
  .settings-page {
    padding-inline: 16px;
  }

  .settings-header h1 {
    font-size: 2.45rem;
  }

  .settings-nav-card {
    grid-template-columns: 1fr;
  }

  .block-head {
    flex-direction: column;
  }
}
</style>

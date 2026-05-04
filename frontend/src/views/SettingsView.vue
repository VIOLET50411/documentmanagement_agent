<template>
  <div class="settings-page">

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
          </button>
        </div>
      </aside>

      <section class="settings-content">
        <div v-if="activeSection === 'general'" class="content-block">
          <div class="block-head">
            <div>
              <h2>通用</h2>
            </div>
          </div>

          <div class="panel-grid">
            <section class="settings-panel">
              <h3>基础资料</h3>
              <div class="form-grid">
                <label class="field">
                  <span>登录账号</span>
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
                  <small>适合白天浏览和长时间阅读。</small>
                </button>
                <button class="theme-card" :class="{ active: themeStore.isDark }" @click="themeStore.setTheme('dark')">
                  <span class="theme-preview theme-dark-preview"></span>
                  <strong>深色模式</strong>
                  <small>适合低光环境，减少眩光和视觉疲劳。</small>
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
                  <strong>对话状态提示</strong>
                  <p>在搜索、阅读、生成等阶段切换时显示简洁状态反馈。</p>
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
              <h2>账号</h2>
            </div>
          </div>

          <section class="settings-panel">
            <div class="info-list">
              <div class="info-row"><span>登录账号</span><strong>{{ user?.username || '-' }}</strong></div>
              <div class="info-row"><span>角色</span><strong>{{ roleLabel(user?.role) }}</strong></div>
              <div class="info-row"><span>邮箱</span><strong>{{ user?.email || '-' }}</strong></div>
              <div class="info-row"><span>邮箱状态</span><strong>{{ user?.email_verified ? '已验证' : '未验证' }}</strong></div>
              <div class="info-row"><span>租户 ID</span><strong>{{ user?.tenant_id || '-' }}</strong></div>
            </div>
          </section>
        </div>

        <div v-else-if="activeSection === 'preferences'" class="content-block">
          <div class="block-head">
            <div>
              <h2>回答偏好</h2>
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
              <span>附加要求</span>
              <select class="input" v-model="responseRequirement">
                <option value="default">优先给结论，提供引用来源</option>
                <option value="detailed">详细展开，按步骤解答</option>
                <option value="concise">极简模式，仅回答核心内容</option>
              </select>
            </label>
          </section>
        </div>

        <SettingsAdminPanels
          v-else-if="['models', 'runtime', 'security', 'mobile'].includes(activeSection)"
          :section="activeSection"
          :is-admin="isAdmin"
          :loading-admin-diagnostics="loadingAdminDiagnostics"
          :llm-domain-config="llmDomainConfig"
          :runtime-metrics="runtimeMetrics"
          :retrieval-integrity="retrievalIntegrity"
          :security-policy="securityPolicy"
          :mobile-auth-status="mobileAuthStatus"
          :push-provider-status="pushProviderStatus"
          :backend-status="backendStatus"
          :format-percent="formatPercent"
          :load-admin-diagnostics="loadAdminDiagnostics"
        />

        <SettingsDevicesPanel
          v-else-if="activeSection === 'devices'"
          :is-native-runtime="isNativeRuntime"
          :native-platform-label="nativePlatformLabel"
          :devices="devices"
          :device-summary="deviceSummary"
          :stored-push-registration="storedPushRegistration"
          :device-form="deviceForm"
          :loading-devices="loadingDevices"
          :loading-events="loadingEvents"
          :loading-summary="loadingSummary"
          :registering="registering"
          :unregistering-token="unregisteringToken"
          :registering-native-push="registeringNativePush"
          :heartbeating-native-push="heartbeatingNativePush"
          :device-message="deviceMessage"
          :native-push-message="nativePushMessage"
          :current-token-status-label="currentTokenStatusLabel"
          :current-token-status-detail="currentTokenStatusDetail"
          :format-date="formatDate"
          :mask-token="maskToken"
          :load-push-data="loadPushData"
          :register-current-device-push="registerCurrentDevicePush"
          :heartbeat-current-device-push="heartbeatCurrentDevicePush"
          :register-device="registerDevice"
          :unregister-device="unregisterDevice"
        />

        <SettingsEventsPanel
          v-else
          :events="events"
          :loading-events="loadingEvents"
          :format-date="formatDate"
          :load-events="loadEvents"
        />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import SettingsAdminPanels from '@/components/settings/SettingsAdminPanels.vue'
import SettingsDevicesPanel from '@/components/settings/SettingsDevicesPanel.vue'
import SettingsEventsPanel from '@/components/settings/SettingsEventsPanel.vue'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import { useSettingsStore } from '@/stores/settings'
import { useThemeStore } from '@/stores/theme'

const responseRequirement = ref('default')

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const notificationsStore = useNotificationsStore()
const settingsStore = useSettingsStore()
const themeStore = useThemeStore()
const user = computed(() => authStore.user)
const isAdmin = computed(() => user.value?.role === 'ADMIN')

const {
  activeSection,
  responseStyle,
  responseLanguage,
  notificationsEnabled,
  statusHintsEnabled,
  loadingAdminDiagnostics,
  llmDomainConfig,
  runtimeMetrics,
  retrievalIntegrity,
  securityPolicy,
  mobileAuthStatus,
  pushProviderStatus,
  backendStatus,
} = storeToRefs(settingsStore)

const {
  isNativeRuntime,
  nativePlatformLabel,
  devices,
  events,
  deviceSummary,
  loadingDevices,
  loadingEvents,
  loadingSummary,
  registering,
  unregisteringToken,
  registeringNativePush,
  heartbeatingNativePush,
  deviceMessage,
  nativePushMessage,
  storedPushRegistration,
  deviceForm,
  currentTokenStatusLabel,
  currentTokenStatusDetail,
} = storeToRefs(notificationsStore)

const sections = [
  { key: 'general', label: '通用', description: '外观、资料与提示' },
  { key: 'account', label: '账号', description: '身份、角色与租户' },
  { key: 'preferences', label: '偏好', description: '回答风格与语言' },
  { key: 'models', label: '模型策略', description: '模型路由与检索完整性' },
  { key: 'runtime', label: '运行时', description: '恢复、断连与后端状态' },
  { key: 'security', label: '安全', description: '策略、审计与 fail-closed' },
  { key: 'mobile', label: '移动端', description: 'OAuth、推送与接入就绪度' },
  { key: 'devices', label: '设备', description: '推送登记与状态' },
  { key: 'events', label: '通知', description: '最近推送事件' },
] as const

type SectionKey = (typeof sections)[number]['key']

watch(
  () => route.query.section,
  (section) => {
    if (typeof section === 'string' && sections.some((item) => item.key === section)) {
      settingsStore.setSection(section as SectionKey)
    }
  },
  { immediate: true }
)

watch(responseStyle, (value) => settingsStore.setResponseStyle(value))
watch(responseLanguage, (value) => settingsStore.setResponseLanguage(value))
watch(notificationsEnabled, (value) => settingsStore.setNotificationsEnabled(value))
watch(statusHintsEnabled, (value) => settingsStore.setStatusHintsEnabled(value))

function setSection(section: string) {
  settingsStore.setSection(section as SectionKey)
  router.replace({ query: { ...route.query, section } })
}

function roleLabel(role?: string) {
  const map: Record<string, string> = {
    ADMIN: '管理员',
    MANAGER: '经理',
    EMPLOYEE: '员工',
    VIEWER: '访客',
  }
  return role ? map[role] || role : '-'
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}

const maskToken = notificationsStore.maskToken

async function loadPushData() {
  await notificationsStore.loadPushData()
}

async function loadEvents() {
  await notificationsStore.loadEvents()
}

async function loadAdminDiagnostics() {
  await settingsStore.loadAdminDiagnostics(isAdmin.value)
}

async function registerCurrentDevicePush() {
  await notificationsStore.registerCurrentDevicePush(user.value?.username)
}

async function heartbeatCurrentDevicePush() {
  await notificationsStore.heartbeatCurrentDevicePush()
}

async function registerDevice() {
  await notificationsStore.registerDevice()
}

async function unregisterDevice(device: any) {
  await notificationsStore.unregisterDevice(device)
}

onMounted(async () => {
  await loadPushData()
  if (isAdmin.value) {
    await loadAdminDiagnostics()
  }
})
</script>

<style scoped>
.settings-page {
  height: 100%;
  overflow-y: auto;
  padding: 6px 22px 28px;
}

.settings-shell {
  max-width: 1440px;
  margin: 0 auto;
}



.settings-shell {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 48px;
  align-items: start;
}

.settings-nav {
  position: sticky;
  top: 18px;
}

.settings-nav-card {
  padding: 0;
  background: transparent;
  border: none;
  box-shadow: none;
  backdrop-filter: none;
}

.settings-tab {
  width: 100%;
  border: none;
  background: transparent;
  border-radius: 6px;
  padding: 10px 14px;
  text-align: left;
  color: var(--text-primary);
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: background-color var(--transition-fast), transform var(--transition-fast);
}

.settings-tab:active {
  transform: scale(0.97);
}

.settings-tab + .settings-tab {
  margin-top: 2px;
}

.settings-tab:hover,
.settings-tab.active {
  background: var(--bg-surface-hover);
}

.settings-tab.active {
  font-weight: 500;
}

.settings-tab-title {
  font-size: 14px;
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
  font-size: 1.25rem;
  font-weight: 600;
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

.form-grid {
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
  transition: all var(--transition-fast);
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

@media (max-width: 1120px) {
  .panel-grid,
  .theme-cards {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 980px) {

  .settings-shell {
    grid-template-columns: 1fr;
    gap: 28px;
  }

  .settings-nav {
    position: static;
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 12px;
    margin-bottom: -12px; /* compensate for padding */
    gap: 8px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none; /* Firefox */
  }

  .settings-nav::-webkit-scrollbar {
    display: none; /* Chrome/Safari */
  }

  .settings-tab {
    white-space: nowrap;
    padding: 8px 16px;
    border-radius: 999px;
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
  }

  .settings-tab.active {
    background: var(--text-primary);
    color: var(--bg-body);
    border-color: var(--text-primary);
  }

  .settings-tab + .settings-tab {
    margin-top: 0;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .settings-page {
    padding-inline: 16px;
  }

  .block-head {
    flex-direction: column;
  }
}
</style>

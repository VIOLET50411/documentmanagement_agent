<template>
  <div class="settings-page">
    <header class="settings-header">
      <div>
        <p class="settings-eyebrow">工作台设置</p>
        <h1>设置</h1>
      </div>
      <p class="settings-summary">统一管理账号、外观、回答偏好、设备接入与推送通知。</p>
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
              <p>控制外观、界面提示和个人资料展示方式。</p>
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
              <p>查看当前登录身份、租户信息和邮箱验证状态。</p>
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
              <p>定义默认输出风格、语言和回答基准。</p>
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

        <div v-else-if="activeSection === 'models'" class="content-block">
          <div class="block-head">
            <div>
              <h2>模型与策略</h2>
              <p>查看企业文档场景下的模型路由、灰度比例和检索完整性状态。</p>
            </div>
            <button v-if="isAdmin" class="btn btn-ghost btn-sm" @click="loadAdminDiagnostics" :disabled="loadingAdminDiagnostics">
              {{ loadingAdminDiagnostics ? '刷新中…' : '刷新' }}
            </button>
          </div>

          <section v-if="!isAdmin" class="settings-panel">
            <p class="empty-text">该部分仅管理员可查看。</p>
          </section>

          <template v-else>
            <section class="settings-panel">
              <h3>企业模型路由</h3>
              <div class="status-grid two-col">
                <div class="status-card">
                  <span>企业模型开关</span>
                  <strong>{{ llmDomainConfig?.enterprise_enabled ? '已开启' : '未开启' }}</strong>
                  <small>控制制度、审批、预算等领域问题是否走企业策略。</small>
                </div>
                <div class="status-card">
                  <span>企业模型名</span>
                  <strong>{{ llmDomainConfig?.enterprise_model_name || '-' }}</strong>
                  <small>当前企业文档场景使用的主模型。</small>
                </div>
                <div class="status-card">
                  <span>灰度比例</span>
                  <strong>{{ llmDomainConfig?.enterprise_canary_percent ?? 0 }}%</strong>
                  <small>企业策略模型当前对租户放量比例。</small>
                </div>
                <div class="status-card">
                  <span>最小语料字符数</span>
                  <strong>{{ llmDomainConfig?.enterprise_corpus_min_chars ?? '-' }}</strong>
                  <small>达到该阈值后才适合企业文档专用策略。</small>
                </div>
              </div>
            </section>

            <section class="settings-panel">
              <h3>检索完整性</h3>
              <div class="status-grid three-col">
                <div class="status-card">
                  <span>健康状态</span>
                  <strong>{{ retrievalIntegrity?.healthy ? '健康' : '待校准' }}</strong>
                  <small>按抽样回查评估当前检索链路是否可用于高置信回答。</small>
                </div>
                <div class="status-card">
                  <span>完整性评分</span>
                  <strong>{{ retrievalIntegrity?.score ?? '-' }}</strong>
                  <small>聚合 ES / Milvus / Graph 的完整性检查结果。</small>
                </div>
                <div class="status-card">
                  <span>Milvus 召回率</span>
                  <strong>{{ formatPercent(retrievalIntegrity?.stats?.milvus_sample_recall) }}</strong>
                  <small>向量检索抽样召回表现。</small>
                </div>
              </div>
              <ul v-if="retrievalIntegrity?.blockers?.length" class="compact-list">
                <li v-for="item in retrievalIntegrity.blockers" :key="item.id">
                  <strong>{{ item.id }}</strong>
                  <span>{{ item.message }}</span>
                </li>
              </ul>
            </section>
          </template>
        </div>

        <div v-else-if="activeSection === 'runtime'" class="content-block">
          <div class="block-head">
            <div>
              <h2>运行时与恢复</h2>
              <p>查看会话恢复、SSE 断连和整体运行指标。</p>
            </div>
            <button v-if="isAdmin" class="btn btn-ghost btn-sm" @click="loadAdminDiagnostics" :disabled="loadingAdminDiagnostics">
              {{ loadingAdminDiagnostics ? '刷新中…' : '刷新' }}
            </button>
          </div>

          <section v-if="!isAdmin" class="settings-panel">
            <p class="empty-text">该部分仅管理员可查看。</p>
          </section>

          <template v-else>
            <section class="settings-panel">
              <h3>Runtime 指标</h3>
              <div class="status-grid three-col">
                <div class="status-card">
                  <span>TTFT P95</span>
                  <strong>{{ runtimeMetrics?.summary?.ttft_ms_p95 ?? '-' }} ms</strong>
                  <small>首字节时间，反映响应起始速度。</small>
                </div>
                <div class="status-card">
                  <span>完成耗时 P95</span>
                  <strong>{{ runtimeMetrics?.summary?.completion_ms_p95 ?? '-' }} ms</strong>
                  <small>整轮回答结束耗时。</small>
                </div>
                <div class="status-card">
                  <span>SSE 断连数</span>
                  <strong>{{ runtimeMetrics?.summary?.sse_disconnects ?? 0 }}</strong>
                  <small>最近采样窗口内的断连累计。</small>
                </div>
                <div class="status-card">
                  <span>回退率</span>
                  <strong>{{ formatPercent(runtimeMetrics?.summary?.fallback_rate) }}</strong>
                  <small>说明真实链路触发降级的比例。</small>
                </div>
                <div class="status-card">
                  <span>拒绝率</span>
                  <strong>{{ formatPercent(runtimeMetrics?.summary?.deny_rate) }}</strong>
                  <small>工具权限网关拒绝调用的比例。</small>
                </div>
                <div class="status-card">
                  <span>平均工具调用</span>
                  <strong>{{ runtimeMetrics?.summary?.avg_tool_calls ?? '-' }}</strong>
                  <small>每轮回答平均触发的工具次数。</small>
                </div>
              </div>
            </section>

            <section class="settings-panel">
              <h3>后端连通性</h3>
              <div class="status-grid three-col">
                <div class="status-card">
                  <span>LLM</span>
                  <strong>{{ backendStatus?.llm?.available ? '在线' : '离线' }}</strong>
                  <small>{{ backendStatus?.llm?.model_name || backendStatus?.llm?.error || '未返回模型信息' }}</small>
                </div>
                <div class="status-card">
                  <span>Milvus</span>
                  <strong>{{ backendStatus?.milvus?.available ? '在线' : '离线' }}</strong>
                  <small>{{ backendStatus?.milvus?.error || '向量检索后端可用' }}</small>
                </div>
                <div class="status-card">
                  <span>Elasticsearch</span>
                  <strong>{{ backendStatus?.elasticsearch?.available ? '在线' : '离线' }}</strong>
                  <small>{{ backendStatus?.elasticsearch?.error || '词法检索后端可用' }}</small>
                </div>
              </div>
            </section>
          </template>
        </div>

        <div v-else-if="activeSection === 'security'" class="content-block">
          <div class="block-head">
            <div>
              <h2>安全与治理</h2>
              <p>查看策略开关、Fail-Closed 状态和高风险链路保护。</p>
            </div>
            <button v-if="isAdmin" class="btn btn-ghost btn-sm" @click="loadAdminDiagnostics" :disabled="loadingAdminDiagnostics">
              {{ loadingAdminDiagnostics ? '刷新中…' : '刷新' }}
            </button>
          </div>

          <section v-if="!isAdmin" class="settings-panel">
            <p class="empty-text">该部分仅管理员可查看。</p>
          </section>

          <template v-else>
            <section class="settings-panel">
              <h3>安全策略状态</h3>
              <div class="status-grid three-col">
                <div class="status-card">
                  <span>总体级别</span>
                  <strong>{{ securityPolicy?.mode || '-' }}</strong>
                  <small>当前安全模式评估结果。</small>
                </div>
                <div class="status-card">
                  <span>Fail-Closed</span>
                  <strong>{{ securityPolicy?.fail_closed ? '开启' : '关闭' }}</strong>
                  <small>高风险链路是否严格失败关闭。</small>
                </div>
                <div class="status-card">
                  <span>审计联动</span>
                  <strong>{{ securityPolicy?.audit_enforced ? '启用' : '未启用' }}</strong>
                  <small>高风险操作是否强制写审计链路。</small>
                </div>
              </div>
              <ul v-if="securityPolicy?.gaps?.length" class="compact-list">
                <li v-for="(item, index) in securityPolicy.gaps" :key="index">
                  <strong>待补齐</strong>
                  <span>{{ item }}</span>
                </li>
              </ul>
            </section>
          </template>
        </div>

        <div v-else-if="activeSection === 'mobile'" class="content-block">
          <div class="block-head">
            <div>
              <h2>移动端接入</h2>
              <p>查看 OAuth2/OIDC、推送提供商和当前租户的移动端 readiness。</p>
            </div>
            <button v-if="isAdmin" class="btn btn-ghost btn-sm" @click="loadAdminDiagnostics" :disabled="loadingAdminDiagnostics">
              {{ loadingAdminDiagnostics ? '刷新中…' : '刷新' }}
            </button>
          </div>

          <section v-if="!isAdmin" class="settings-panel">
            <p class="empty-text">该部分仅管理员可查看。</p>
          </section>

          <template v-else>
            <section class="settings-panel">
              <h3>移动认证状态</h3>
              <div class="status-grid two-col">
                <div class="status-card">
                  <span>OAuth/OIDC</span>
                  <strong>{{ mobileAuthStatus?.enabled ? '已启用' : '未启用' }}</strong>
                  <small>{{ mobileAuthStatus?.issuer || '未返回 issuer 信息' }}</small>
                </div>
                <div class="status-card">
                  <span>PKCE</span>
                  <strong>{{ mobileAuthStatus?.pkce_required ? '强制' : '未强制' }}</strong>
                  <small>移动端授权码流程是否要求 PKCE。</small>
                </div>
              </div>
            </section>

            <section class="settings-panel">
              <h3>推送提供商状态</h3>
              <div class="status-grid three-col">
                <div class="status-card">
                  <span>FCM</span>
                  <strong>{{ pushProviderStatus?.providers?.fcm?.ready ? '已就绪' : '未就绪' }}</strong>
                  <small>{{ pushProviderStatus?.providers?.fcm?.reason || 'Android 推送通道' }}</small>
                </div>
                <div class="status-card">
                  <span>APNs</span>
                  <strong>{{ pushProviderStatus?.providers?.apns?.ready ? '已就绪' : '未就绪' }}</strong>
                  <small>{{ pushProviderStatus?.providers?.apns?.reason || 'iOS 推送通道' }}</small>
                </div>
                <div class="status-card">
                  <span>微信小程序</span>
                  <strong>{{ pushProviderStatus?.providers?.wechat?.ready ? '已就绪' : '未就绪' }}</strong>
                  <small>{{ pushProviderStatus?.providers?.wechat?.reason || '订阅消息通道' }}</small>
                </div>
              </div>
            </section>
          </template>
        </div>

        <div v-else-if="activeSection === 'devices'" class="content-block">
          <div class="block-head">
            <div>
              <h2>设备</h2>
              <p>登记推送设备，用于移动端、桌面端或 Web 的状态提醒。</p>
            </div>
            <button class="btn btn-ghost btn-sm" @click="loadPushData" :disabled="loadingDevices || loadingEvents || loadingSummary">
              {{ loadingDevices || loadingEvents || loadingSummary ? '刷新中…' : '刷新' }}
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
                {{ registeringNativePush ? '注册中…' : '自动注册当前设备' }}
              </button>
              <button class="btn btn-ghost" :disabled="heartbeatingNativePush || !storedPushRegistration" @click="heartbeatCurrentDevicePush">
                {{ heartbeatingNativePush ? '续期中…' : '发送一次心跳' }}
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
                  <option value="ios">iOS</option>
                  <option value="web">Web</option>
                  <option value="wechat">微信小程序</option>
                </select>
              </label>

              <label class="field">
                <span>设备名称</span>
                <input v-model="deviceForm.device_name" class="input" type="text" placeholder="例如 Pixel 8 / iPhone 15 / 浏览器" />
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
                  <td>
                    <span class="badge" :class="device.is_active ? 'badge-success' : 'badge-muted'">
                      {{ device.is_active ? '已启用' : '已停用' }}
                    </span>
                  </td>
                  <td>{{ formatDate(device.last_seen_at || device.updated_at) }}</td>
                  <td>
                    <button class="btn btn-ghost btn-sm" :disabled="unregisteringToken === device.device_token" @click="unregisterDevice(device)">
                      {{ unregisteringToken === device.device_token ? '注销中…' : '注销' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else class="empty-text">当前还没有登记过推送设备。</p>
          </section>
        </div>

        <div v-else class="content-block">
          <div class="block-head">
            <div>
              <h2>通知记录</h2>
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
import { computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import { useSettingsStore } from '@/stores/settings'
import { useThemeStore } from '@/stores/theme'

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
  { key: 'mobile', label: '移动端', description: 'OAuth、推送与接入 readiness' },
  { key: 'devices', label: '设备', description: '推送登记与状态' },
  { key: 'events', label: '通知', description: '最近推送事件' },
] as const

watch(
  () => route.query.section,
  (section) => {
    if (typeof section === 'string' && sections.some((item) => item.key === section)) {
      settingsStore.setSection(section as (typeof sections)[number]['key'])
    }
  },
  { immediate: true }
)

watch(responseStyle, (value) => settingsStore.setResponseStyle(value))
watch(responseLanguage, (value) => settingsStore.setResponseLanguage(value))
watch(notificationsEnabled, (value) => settingsStore.setNotificationsEnabled(value))
watch(statusHintsEnabled, (value) => settingsStore.setStatusHintsEnabled(value))

function setSection(section: string) {
  settingsStore.setSection(section as (typeof sections)[number]['key'])
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

.panel-copy {
  color: var(--text-secondary);
  margin-bottom: 14px;
}

.device-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.helper-text {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.status-grid.two-col {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.status-grid.three-col {
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
.status-card small {
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

.compact-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.compact-list li {
  list-style: none;
  padding: 14px 16px;
  border-radius: 18px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-color-subtle);
}

.compact-list strong,
.compact-list span {
  display: block;
}

.compact-list span {
  margin-top: 6px;
  color: var(--text-secondary);
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
  .theme-cards,
  .status-grid {
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

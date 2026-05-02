<template>
  <div class="app-layout">
    <aside class="sidebar" :class="{ expanded: isSidebarOpen }">
      <div class="sidebar-inner">
        <div class="sidebar-top">
          <button
            class="sidebar-toggle"
            :class="{ active: isSidebarOpen }"
            aria-label="切换侧边栏"
            @click="toggleSidebar"
          >
            <span></span>
            <span></span>
          </button>
          <button v-if="isSidebarOpen" class="brand-button" @click="$router.push('/chat')">
            <span class="brand-mark">D</span>
            <span class="brand-copy">
              <strong>DocMind</strong>
              <small>企业文档智能工作台</small>
            </span>
          </button>
        </div>

        <nav class="sidebar-nav">
          <button
            v-for="item in visibleNavItems"
            :key="item.key"
            class="nav-item"
            :class="{ current: isCurrent(item) }"
            :title="item.label"
            @click="handleNav(item)"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            <span class="nav-copy">
              <strong>{{ item.label }}</strong>
              <small>{{ item.description }}</small>
            </span>
          </button>
        </nav>

        <section v-if="isSidebarOpen" class="sidebar-section">
          <div class="section-head">
            <p>最近会话</p>
            <button class="section-link" @click="startNewChat">新建</button>
          </div>
          <div class="recent-list">
            <button
              v-for="session in recentSessions"
              :key="session.id"
              class="recent-item"
              :class="{ active: route.name === 'Chat' && chatStore.activeSessionId === session.id }"
              @click="openRecentSession(session.id)"
            >
              <strong>{{ session.title }}</strong>
              <span>{{ formatTime(session.updatedAt) }}</span>
            </button>
            <p v-if="recentSessions.length === 0" class="empty-copy">还没有历史会话</p>
          </div>
        </section>

        <div class="sidebar-spacer"></div>

        <div class="sidebar-bottom">
          <div class="account-shell">
            <button class="account-trigger" :class="{ active: accountMenuOpen }" @click.stop="toggleAccountMenu">
              <div class="account-avatar">{{ initials }}</div>
              <div v-if="isSidebarOpen" class="account-meta">
                <strong>{{ user?.username || '演示用户' }}</strong>
                <span>{{ roleLabel(user?.role) }}</span>
              </div>
              <span v-if="isSidebarOpen" class="account-caret">⌄</span>
            </button>

            <transition name="menu-pop">
              <div v-if="accountMenuOpen" class="account-menu" @click.stop>
                <div class="menu-profile">
                  <div class="menu-avatar">{{ initials }}</div>
                  <div class="menu-profile-copy">
                    <strong>{{ user?.username || '演示用户' }}</strong>
                    <span>{{ user?.email || '未设置邮箱' }}</span>
                  </div>
                </div>

                <div class="menu-group">
                  <button class="menu-item" @click="openSettings('general')">
                    <span>通用设置</span>
                    <small>外观、资料与基础偏好</small>
                  </button>
                  <button class="menu-item" @click="openSettings('preferences')">
                    <span>回答偏好</span>
                    <small>语言、风格与默认要求</small>
                  </button>
                  <button class="menu-item" @click="openSettings('devices')">
                    <span>推送设备</span>
                    <small>移动端、网页端与小程序</small>
                  </button>
                </div>

                <div class="menu-group menu-inline-group">
                  <button class="menu-item menu-inline" @click="themeStore.setTheme('light')">
                    <span>浅色模式</span>
                    <small v-if="!themeStore.isDark">当前使用</small>
                  </button>
                  <button class="menu-item menu-inline" @click="themeStore.setTheme('dark')">
                    <span>深色模式</span>
                    <small v-if="themeStore.isDark">当前使用</small>
                  </button>
                </div>

                <div class="menu-group">
                  <button v-if="user?.role === 'ADMIN'" class="menu-item" @click="$router.push('/admin')">
                    <span>平台管理</span>
                    <small>运行指标、任务与审计</small>
                  </button>
                  <button class="menu-item danger" @click="authStore.logout">
                    <span>退出登录</span>
                    <small>结束当前会话</small>
                  </button>
                </div>
              </div>
            </transition>
          </div>
        </div>
      </div>
    </aside>

    <main class="content-shell" @click="accountMenuOpen = false">
      <header class="topbar">
        <div class="topbar-copy">
          <p class="topbar-kicker">{{ pageKicker }}</p>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="topbar-actions">
          <button v-if="route.name === 'Chat'" class="btn btn-ghost" @click="startNewChat">新建对话</button>
          <button class="theme-chip" @click="themeStore.toggle()">
            {{ themeStore.isDark ? '深色' : '浅色' }}
          </button>
        </div>
      </header>

      <section class="content-body">
        <router-view />
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useThemeStore } from '@/stores/theme'

type NavItem = {
  key: string
  label: string
  description: string
  icon: string
  route?: string
  action?: 'new'
  adminOnly?: boolean
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()
const chatStore = useChatStore()

const user = computed(() => authStore.user)
const initials = computed(() => (user.value?.username || 'D').slice(0, 1).toUpperCase())
const recentSessions = computed(() => chatStore.sessions.slice(0, 8))
const isSidebarOpen = ref(true)
const accountMenuOpen = ref(false)

const navItems: NavItem[] = [
  { key: 'new', label: '新建对话', description: '开始一轮新的问答', icon: '+', action: 'new' },
  { key: 'chat', label: '会话记录', description: '查看与切换历史对话', icon: '◉', route: '/chat' },
  { key: 'search', label: '知识检索', description: '搜索索引、图谱与证据', icon: '⌕', route: '/search' },
  { key: 'documents', label: '文档中心', description: '上传、解析与处理文档', icon: '▣', route: '/documents' },
  { key: 'settings', label: '个人设置', description: '账号、主题与设备偏好', icon: '⚙', route: '/settings' },
  { key: 'admin', label: '平台管理', description: '运行态、审计与任务看板', icon: '▤', route: '/admin', adminOnly: true },
]

const visibleNavItems = computed(() => navItems.filter((item) => !item.adminOnly || user.value?.role === 'ADMIN'))

const pageTitle = computed(() => {
  if (route.name === 'Chat' && chatStore.messages.length > 0) {
    return chatStore.activeSession?.title || '当前对话'
  }
  const current = visibleNavItems.value.find((item) => item.route === route.path)
  return current?.label || 'DocMind'
})

const pageKicker = computed(() => {
  const map: Record<string, string> = {
    Chat: '智能问答',
    Documents: '文档处理',
    Search: '证据检索',
    Settings: '个人偏好',
    Admin: '平台运营',
  }
  return map[String(route.name || '')] || 'DocMind'
})

watch(
  () => ({ name: route.name, messageCount: chatStore.messages.length }),
  ({ name, messageCount }) => {
    if (name === 'Chat' && messageCount > 0) {
      isSidebarOpen.value = false
    }
  },
  { immediate: true }
)

watch(
  () => route.fullPath,
  () => {
    accountMenuOpen.value = false
  }
)

function toggleSidebar() {
  isSidebarOpen.value = !isSidebarOpen.value
  if (!isSidebarOpen.value) {
    accountMenuOpen.value = false
  }
}

function toggleAccountMenu() {
  accountMenuOpen.value = !accountMenuOpen.value
}

function handleNav(item: NavItem) {
  accountMenuOpen.value = false
  if (item.action === 'new') {
    startNewChat()
    return
  }
  if (item.route) {
    router.push(item.route)
  }
}

function isCurrent(item: NavItem) {
  return item.route ? route.path === item.route : false
}

function startNewChat() {
  chatStore.createSession()
  router.push('/chat')
  isSidebarOpen.value = false
}

async function openRecentSession(sessionId: string) {
  await chatStore.setActiveSession(sessionId)
  router.push('/chat')
  isSidebarOpen.value = false
}

function openSettings(section: string) {
  accountMenuOpen.value = false
  router.push({ path: '/settings', query: { section } })
}

function roleLabel(role?: string) {
  const map: Record<string, string> = {
    ADMIN: '管理员',
    MANAGER: '经理',
    EMPLOYEE: '成员',
    VIEWER: '访客',
  }
  return map[role || ''] || role || '未登录'
}

function formatTime(value: string) {
  const target = new Date(value)
  if (Number.isNaN(target.getTime())) return value
  const diff = Date.now() - target.getTime()
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚更新'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`
  return `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}-${String(target.getDate()).padStart(2, '0')}`
}

function handleGlobalClick() {
  accountMenuOpen.value = false
}

onMounted(() => {
  window.addEventListener('click', handleGlobalClick)
})

onBeforeUnmount(() => {
  window.removeEventListener('click', handleGlobalClick)
})
</script>

<style scoped>
.app-layout {
  display: grid;
  grid-template-columns: auto 1fr;
  min-height: 100vh;
}

.sidebar {
  width: var(--sidebar-collapsed-width);
  min-width: var(--sidebar-collapsed-width);
  border-right: 1px solid var(--border-color);
  background: color-mix(in srgb, var(--bg-sidebar) 92%, transparent);
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
  transition: width var(--transition-slow), min-width var(--transition-slow), background-color var(--transition-base);
  overflow: hidden;
}

.sidebar.expanded {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 18px 14px;
  gap: 18px;
}

.sidebar-top,
.sidebar-bottom {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sidebar-toggle {
  width: 44px;
  height: 44px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.36);
  display: grid;
  place-items: center;
  gap: 4px;
  transition: transform var(--transition-fast), border-color var(--transition-fast), background-color var(--transition-fast);
}

.sidebar-toggle span {
  display: block;
  width: 16px;
  height: 2px;
  border-radius: 999px;
  background: var(--text-primary);
  transition: transform var(--transition-fast), opacity var(--transition-fast);
}

.sidebar-toggle.active span:first-child { transform: translateY(3px) rotate(45deg); }
.sidebar-toggle.active span:last-child { transform: translateY(-3px) rotate(-45deg); }

.brand-button {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 0;
  background: transparent;
  text-align: left;
}

.brand-mark,
.account-avatar,
.menu-avatar {
  width: 40px;
  height: 40px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, rgba(36, 31, 23, 0.96), rgba(87, 71, 48, 0.84));
  color: #fff8ef;
  font-weight: 700;
}

.brand-copy,
.account-meta,
.menu-profile-copy,
.nav-copy {
  min-width: 0;
}

.brand-copy strong,
.account-meta strong,
.menu-profile-copy strong,
.nav-copy strong {
  display: block;
  font-family: "Manrope", "PingFang SC", "Microsoft YaHei UI", sans-serif;
  font-weight: 700;
  color: var(--text-primary);
}

.brand-copy small,
.account-meta span,
.menu-profile-copy span,
.nav-copy small {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-nav,
.recent-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nav-item,
.recent-item,
.account-trigger,
.menu-item,
.section-link,
.theme-chip {
  border: 0;
  background: transparent;
}

.nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 18px;
  color: var(--text-secondary);
  transition: background-color var(--transition-base), color var(--transition-fast), transform var(--transition-fast);
  overflow: hidden;
}

.nav-item:hover,
.recent-item:hover,
.account-trigger:hover,
.menu-item:hover,
.theme-chip:hover,
.section-link:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}

.nav-item.current {
  background: var(--bg-surface-strong);
  color: var(--text-primary);
  box-shadow: inset 0 0 0 1px var(--border-color-subtle), 0 12px 28px rgba(36, 31, 23, 0.06);
}

.nav-icon {
  width: 32px;
  min-width: 32px;
  height: 32px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.56);
  font-size: 15px;
  color: inherit;
}

.sidebar:not(.expanded) .nav-copy,
.sidebar:not(.expanded) .brand-button,
.sidebar:not(.expanded) .sidebar-section,
.sidebar:not(.expanded) .account-meta,
.sidebar:not(.expanded) .account-caret {
  opacity: 0;
  width: 0;
  pointer-events: none;
}

.sidebar-section {
  padding: 12px;
  border: 1px solid var(--border-color-subtle);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.34);
  transition: opacity var(--transition-base), transform var(--transition-base);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.section-head p {
  font-size: 12px;
  color: var(--text-secondary);
}

.section-link {
  font-size: 12px;
  color: var(--text-link);
  padding: 4px 8px;
  border-radius: 999px;
}

.recent-item {
  width: 100%;
  padding: 10px 12px;
  text-align: left;
  border-radius: 16px;
  transition: background-color var(--transition-fast), transform var(--transition-fast);
}

.recent-item strong,
.recent-item span {
  display: block;
}

.recent-item strong {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-item span,
.empty-copy {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.recent-item.active {
  background: var(--bg-surface-strong);
}

.sidebar-spacer { flex: 1; }

.account-shell { position: relative; width: 100%; }

.account-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px;
  border-radius: 20px;
  transition: background-color var(--transition-base), box-shadow var(--transition-base);
}

.account-trigger.active {
  background: var(--bg-surface-strong);
  box-shadow: inset 0 0 0 1px var(--border-color-subtle);
}

.account-caret {
  margin-left: auto;
  color: var(--text-tertiary);
}

.account-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 12px);
  width: min(320px, calc(100vw - 32px));
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 24px;
  background: var(--bg-surface-strong);
  box-shadow: var(--shadow-md);
  z-index: 50;
}

.menu-profile {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 8px 14px;
}

.menu-group {
  display: grid;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color-subtle);
}

.menu-inline-group {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.menu-item {
  width: 100%;
  display: block;
  padding: 12px 14px;
  text-align: left;
  border-radius: 18px;
  transition: background-color var(--transition-fast);
}

.menu-item span,
.menu-item small {
  display: block;
}

.menu-item span {
  color: var(--text-primary);
  font-weight: 600;
}

.menu-item small {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.menu-item.danger span { color: var(--color-danger); }
.menu-item-inline { text-align: center; }

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 28px 18px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--bg-app) 88%, transparent), transparent);
  backdrop-filter: blur(12px);
}

.topbar-kicker {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.topbar h1 {
  margin-top: 6px;
  font-size: clamp(1.1rem, 1vw + 0.95rem, 1.55rem);
  line-height: 1.2;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.theme-chip {
  padding: 10px 14px;
  border-radius: 999px;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.42);
}

.content-shell {
  min-width: 0;
  min-height: 100vh;
}

.content-body {
  padding: 0 24px 24px;
}

.menu-pop-enter-active,
.menu-pop-leave-active {
  transition: opacity var(--transition-base), transform var(--transition-base);
}

.menu-pop-enter-from,
.menu-pop-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

@media (max-width: 1024px) {
  .app-layout {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    z-index: 40;
  }

  .content-shell {
    padding-left: var(--sidebar-collapsed-width);
  }

  .sidebar.expanded + .content-shell {
    padding-left: var(--sidebar-width);
  }
}

@media (max-width: 768px) {
  .content-shell,
  .sidebar.expanded + .content-shell {
    padding-left: 0;
  }

  .sidebar {
    transform: translateX(calc(-100% + var(--sidebar-collapsed-width)));
  }

  .sidebar.expanded {
    transform: translateX(0);
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.18);
  }

  .topbar {
    padding: 18px 18px 14px 88px;
  }

  .content-body {
    padding: 0 14px 18px;
  }
}
</style>

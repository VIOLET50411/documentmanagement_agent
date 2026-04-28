<template>
  <div class="app-layout">
    <aside class="sidebar" :class="{ expanded: isSidebarOpen }">
      <div class="sidebar-top">
        <button
          class="sidebar-toggle"
          :class="{ active: isSidebarOpen }"
          aria-label="切换侧边栏"
          @click="toggleSidebar"
        >
          <span class="toggle-grid"></span>
        </button>
        <button v-if="isSidebarOpen" class="brand-button" @click="$router.push('/chat')">DocMind</button>
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
          <span class="nav-text">{{ item.label }}</span>
        </button>
      </nav>

      <transition name="sidebar-fade">
        <section v-if="isSidebarOpen" class="sidebar-section">
          <p class="section-title">最近会话</p>
          <button
            v-for="session in recentSessions"
            :key="session.id"
            class="recent-item"
            :class="{ active: route.name === 'Chat' && chatStore.activeSessionId === session.id }"
            @click="openRecentSession(session.id)"
          >
            {{ session.title }}
          </button>
          <p v-if="recentSessions.length === 0" class="empty-copy">还没有历史会话</p>
        </section>
      </transition>

      <div class="sidebar-spacer"></div>

      <div class="sidebar-bottom">
        <div class="account-shell">
          <button class="account-trigger" :class="{ active: accountMenuOpen }" @click.stop="toggleAccountMenu">
            <div class="account-avatar">{{ initials }}</div>
            <div v-if="isSidebarOpen" class="account-meta">
              <strong>{{ user?.username || '演示用户' }}</strong>
              <span>{{ roleLabel(user?.role) }}</span>
            </div>
            <span v-if="isSidebarOpen" class="account-caret">▴</span>
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
                  <span>设置</span>
                  <small>通用与外观</small>
                </button>
                <button class="menu-item" @click="openSettings('preferences')">
                  <span>回答偏好</span>
                  <small>输出风格与语言</small>
                </button>
                <button class="menu-item" @click="openSettings('devices')">
                  <span>推送设备</span>
                  <small>移动端与 Web 推送</small>
                </button>
              </div>

              <div class="menu-group menu-theme">
                <button class="menu-item menu-item-inline" @click="themeStore.setTheme('light')">
                  <span>浅色模式</span>
                  <small v-if="!themeStore.isDark">当前使用</small>
                </button>
                <button class="menu-item menu-item-inline" @click="themeStore.setTheme('dark')">
                  <span>深色模式</span>
                  <small v-if="themeStore.isDark">当前使用</small>
                </button>
              </div>

              <div class="menu-group">
                <button v-if="user?.role === 'ADMIN'" class="menu-item" @click="$router.push('/admin')">
                  <span>平台管理</span>
                  <small>运行状态与审计面板</small>
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
    </aside>

    <main class="content-shell" @click="accountMenuOpen = false">
      <div class="top-utility">
        <div class="top-title" v-if="showConversationHeader">
          <button class="title-button">{{ conversationTitle }}</button>
        </div>
        <div class="top-actions">
          <button v-if="showConversationHeader" class="share-button">分享</button>
          <button class="ghostmark" aria-label="消息中心">◎</button>
        </div>
      </div>

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
const showConversationHeader = computed(() => route.name === 'Chat' && chatStore.messages.length > 0)
const conversationTitle = computed(() => chatStore.activeSession?.title || '新对话')
const isSidebarOpen = ref(true)
const accountMenuOpen = ref(false)

const navItems: NavItem[] = [
  { key: 'new', label: '新建对话', icon: '+', action: 'new' },
  { key: 'search', label: '知识检索', icon: '⌕', route: '/search' },
  { key: 'chat', label: '对话记录', icon: '◌', route: '/chat' },
  { key: 'documents', label: '文档中心', icon: '▣', route: '/documents' },
  { key: 'admin', label: '平台管理', icon: '⚙', route: '/admin', adminOnly: true },
  { key: 'settings', label: '个人设置', icon: '◐', route: '/settings' },
]

const visibleNavItems = computed(() => navItems.filter((item) => !item.adminOnly || user.value?.role === 'ADMIN'))

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
  display: flex;
  min-height: 100vh;
  background: transparent;
}

.sidebar {
  width: 74px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color-subtle);
  background: color-mix(in srgb, var(--bg-sidebar) 92%, transparent);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  overflow: visible;
  transition:
    width 260ms cubic-bezier(0.2, 0.8, 0.2, 1),
    background-color var(--transition-base),
    border-color var(--transition-base);
}

.sidebar.expanded {
  width: 308px;
}

.sidebar-top {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  min-height: 72px;
}

.sidebar-toggle {
  width: 40px;
  height: 40px;
  min-width: 40px;
  border: none;
  border-radius: 14px;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color var(--transition-fast), transform var(--transition-fast);
}

.sidebar-toggle:hover,
.sidebar-toggle.active {
  background: var(--bg-surface-hover);
}

.sidebar-toggle:hover {
  transform: translateY(-1px);
}

.toggle-grid {
  width: 16px;
  height: 12px;
  border: 1.5px solid currentColor;
  border-radius: 2px;
  position: relative;
}

.toggle-grid::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 50%;
  width: 1.5px;
  background: currentColor;
  transform: translateX(-50%);
}

.brand-button {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: 2rem;
  font-weight: 600;
  letter-spacing: -0.04em;
  cursor: pointer;
}

.sidebar-nav,
.sidebar-section,
.sidebar-bottom {
  padding: 0 12px;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item,
.recent-item,
.account-trigger,
.menu-item,
.title-button,
.share-button,
.ghostmark {
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast),
    transform var(--transition-fast);
}

.nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 14px;
  height: 46px;
  padding: 0 8px;
  border: none;
  border-radius: 14px;
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.nav-item:hover,
.nav-item.current {
  background: var(--bg-surface-hover);
}

.nav-icon {
  width: 38px;
  min-width: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  color: var(--text-secondary);
}

.nav-item.current .nav-icon,
.nav-item.current .nav-text {
  color: var(--text-primary);
}

.nav-text,
.account-meta {
  white-space: nowrap;
  opacity: 0;
  transform: translateX(-8px);
  transition: opacity 160ms ease, transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.sidebar.expanded .nav-text,
.sidebar.expanded .account-meta {
  opacity: 1;
  transform: translateX(0);
}

.sidebar-section {
  margin-top: 18px;
}

.section-title {
  margin: 0 8px 12px;
  color: var(--text-tertiary);
  font-size: 0.9rem;
}

.recent-item {
  width: 100%;
  border: none;
  background: transparent;
  padding: 10px 10px;
  border-radius: 14px;
  color: var(--text-secondary);
  font-size: 0.95rem;
  text-align: left;
  cursor: pointer;
}

.recent-item:hover,
.recent-item.active {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}

.empty-copy {
  margin: 0 8px;
  color: var(--text-tertiary);
  font-size: 0.9rem;
}

.sidebar-spacer {
  flex: 1;
}

.sidebar-bottom {
  padding-bottom: 12px;
}

.account-shell {
  position: relative;
}

.account-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 8px;
  border: none;
  border-radius: 16px;
  background: transparent;
  cursor: pointer;
}

.account-trigger:hover,
.account-trigger.active {
  background: var(--bg-surface-hover);
}

.account-avatar,
.menu-avatar {
  width: 38px;
  height: 38px;
  min-width: 38px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--text-primary), #6f665c);
  color: var(--bg-surface-strong);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.menu-avatar {
  width: 42px;
  height: 42px;
  min-width: 42px;
}

.account-meta {
  flex: 1;
  min-width: 0;
  text-align: left;
}

.account-meta strong,
.menu-profile-copy strong {
  display: block;
  font-size: 0.94rem;
  color: var(--text-primary);
}

.account-meta span,
.menu-profile-copy span,
.account-caret {
  color: var(--text-secondary);
  font-size: 0.84rem;
}

.account-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 12px);
  width: 290px;
  border: 1px solid var(--border-color);
  border-radius: 24px;
  background: color-mix(in srgb, var(--bg-surface-strong) 96%, transparent);
  box-shadow: var(--shadow-lg);
  padding: 10px;
  z-index: 40;
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
}

.menu-profile {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 8px 14px;
}

.menu-profile-copy span {
  display: block;
  margin-top: 4px;
  word-break: break-all;
}

.menu-group + .menu-group {
  border-top: 1px solid var(--border-color-subtle);
  margin-top: 8px;
  padding-top: 8px;
}

.menu-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  border: none;
  background: transparent;
  text-align: left;
  padding: 12px 12px;
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 0.98rem;
  cursor: pointer;
}

.menu-item:hover {
  background: var(--bg-surface-hover);
}

.menu-item small {
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.menu-theme {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.menu-item-inline {
  min-height: 72px;
  justify-content: center;
}

.menu-item.danger span {
  color: var(--color-danger);
}

.content-shell {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.top-utility {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px 0 22px;
}

.title-button {
  border: none;
  background: transparent;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  cursor: default;
}

.top-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.share-button {
  border: 1px solid var(--border-color);
  background: color-mix(in srgb, var(--bg-surface-strong) 90%, transparent);
  border-radius: 14px;
  padding: 10px 16px;
  font-weight: 600;
  cursor: pointer;
  color: var(--text-primary);
}

.share-button:hover,
.ghostmark:hover {
  background: var(--bg-surface-hover);
}

.ghostmark {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
  color: var(--text-secondary);
}

.content-body {
  flex: 1;
  min-height: 0;
}

.sidebar-fade-enter-active,
.sidebar-fade-leave-active {
  transition: opacity 180ms ease, transform 220ms ease;
}

.sidebar-fade-enter-from,
.sidebar-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

.menu-pop-enter-active,
.menu-pop-leave-active {
  transition: opacity 180ms ease, transform 220ms cubic-bezier(0.16, 1, 0.3, 1);
  transform-origin: left bottom;
}

.menu-pop-enter-from,
.menu-pop-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.97);
}

@media (max-width: 980px) {
  .sidebar.expanded {
    width: 282px;
  }

  .account-menu {
    width: 270px;
  }

  .top-utility {
    padding-right: 16px;
  }
}
</style>

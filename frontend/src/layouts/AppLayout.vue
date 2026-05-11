<template>
  <div class="app-layout">
    <div class="mobile-overlay" :class="{ visible: isSidebarOpen }" @click="isSidebarOpen = false"></div>
    <aside class="sidebar" :class="{ expanded: isSidebarOpen }">
      <div class="sidebar-inner">
        <div class="sidebar-top">
          <button
            class="sidebar-toggle"
            :class="{ active: isSidebarOpen }"
            aria-label="切换侧边栏"
            @click="toggleSidebar"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="9" y1="3" x2="9" y2="21"></line>
            </svg>
          </button>
          <button class="brand-button" @click="$router.push('/chat')">
            <span class="brand-text">DocMind</span>
          </button>
        </div>

        <nav class="sidebar-nav">
          <button
            v-for="item in visibleNavItems"
            :key="item.key"
            class="nav-item"
            :class="{ current: isCurrent(item), 'icon-only': !isSidebarOpen }"
            :title="item.label"
            @click="handleNav(item)"
          >
            <span class="nav-icon" v-html="item.icon"></span>
            <span class="nav-label">{{ item.label }}</span>
          </button>
        </nav>

        <section class="sidebar-section">
          <div class="section-head">
            <p>最近会话</p>
            <button class="section-link" @click="startNewChat">新建</button>
          </div>
          <div class="recent-list">
            <div
              v-for="session in recentSessions"
              :key="session.id"
              class="recent-item-wrapper"
              style="display: flex; gap: 4px; align-items: center;"
            >
              <button
                class="recent-item"
                :class="{ active: route.name === 'Chat' && chatStore.activeSessionId === session.id }"
                @click="openRecentSession(session.id)"
                style="flex: 1; min-width: 0;"
              >
                <strong>{{ session.title }}</strong>
                <span>{{ formatTime(session.updatedAt) }}</span>
              </button>
              <button
                class="delete-session-btn"
                @click.stop="chatStore.deleteSession(session.id)"
                style="padding: 6px; background: transparent; border: none; cursor: pointer; color: var(--text-secondary); transition: color var(--transition-fast);"
                onmouseover="this.style.color='var(--text-primary)'"
                onmouseout="this.style.color='var(--text-secondary)'"
                title="删除会话"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"></polyline>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                </svg>
              </button>
            </div>
            <p v-if="recentSessions.length === 0" class="empty-copy">还没有历史会话</p>
          </div>
        </section>

        <div class="sidebar-spacer"></div>

        <div class="sidebar-bottom">
          <div class="account-shell">
            <button class="account-trigger" :class="{ active: accountMenuOpen }" @click.stop="toggleAccountMenu">
              <div class="account-avatar">{{ initials }}</div>
              <div class="account-meta">
                <strong>{{ user?.username || 'admin_demo' }}</strong>
                <span>{{ roleLabel(user?.role) }}</span>
              </div>
            </button>

            <teleport to="body">
              <transition name="menu-pop">
                <div v-if="accountMenuOpen" class="account-menu" :style="{ left: isSidebarOpen ? '20px' : '10px' }" @click.stop>
                  <div class="menu-email">
                    {{ user?.email || user?.username || 'admin_demo@docmind.local' }}
                  </div>

                  <div class="menu-group">
                    <button class="menu-item" @click="openSettings('general')">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                      <span>个人设置</span>
                    </button>
                  </div>

                  <div class="menu-group">
                    <button class="menu-item" @click="themeStore.setTheme(themeStore.isDark ? 'light' : 'dark')">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
                      <span>切换主题</span>
                    </button>
                    <button v-if="user?.role === 'ADMIN'" class="menu-item" @click="$router.push('/admin')">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
                      <span>平台管理</span>
                    </button>
                  </div>

                  <div class="menu-group border-none">
                    <button class="menu-item" @click="authStore.logout">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
                      <span>退出登录</span>
                    </button>
                  </div>
                </div>
              </transition>
            </teleport>
          </div>
        </div>
      </div>
    </aside>

    <main class="content-shell" @click="accountMenuOpen = false">
      <header class="topbar">
        <div class="topbar-left">
          <button class="mobile-menu-btn" @click="isSidebarOpen = true">
             <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
          </button>
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
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
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

const svgIcons = {
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>',
  new: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
  tasks: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
  documents: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-2.82.13 1.65 1.65 0 0 0-.13 2.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>',
  admin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path></svg>'
}

const navItems: NavItem[] = [
  { key: 'new', label: '新建对话', description: '开始一轮新的问答', icon: svgIcons.new, action: 'new' },
  { key: 'tasks', label: '任务中心', description: '查看运行、入库与训练任务', icon: svgIcons.tasks, route: '/tasks', adminOnly: true },
  { key: 'search', label: '知识检索', description: '搜索索引、图谱与证据', icon: svgIcons.search, route: '/search' },
  { key: 'documents', label: '文档中心', description: '上传、解析与处理文档', icon: svgIcons.documents, route: '/documents' },
]

const visibleNavItems = computed(() => navItems.filter((item) => !item.adminOnly || user.value?.role === 'ADMIN'))

const pageTitle = computed(() => {
  if (route.name === 'Chat') {
    return chatStore.activeSession?.title || '当前对话'
  }
  const routeLabels: Record<string, string> = {
    '/settings': '个人设置',
    '/admin': '平台管理'
  }
  if (routeLabels[route.path]) {
    return routeLabels[route.path]
  }
  const current = visibleNavItems.value.find((item) => item.route === route.path)
  return current?.label || 'DocMind'
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
  void chatStore.initialize()
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
  height: 100vh;
  position: sticky;
  top: 0;
  border-right: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  transition: width var(--transition-slow), min-width var(--transition-slow);
  overflow-x: hidden;
  overflow-y: auto;
  z-index: 30;
}

.sidebar.expanded {
  width: 260px;
  min-width: 260px;
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
  width: 32px;
  height: 32px;
  border: 0;
  background: transparent;
  display: grid;
  place-items: center;
  gap: 4px;
  transition: opacity var(--transition-fast);
  cursor: pointer;
  color: var(--text-secondary);
}

.sidebar-toggle span {
  display: block;
  width: 14px;
  height: 1.5px;
  border-radius: 999px;
  background: currentColor;
  transition: transform var(--transition-fast), opacity var(--transition-fast);
}

.sidebar-toggle:hover {
  color: var(--text-primary);
}

.brand-button {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.brand-text {
  font-family: var(--font-heading);
  font-size: 1.25rem;
  font-weight: 400;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.account-avatar,
.menu-avatar {
  width: 32px;
  height: 32px;
  min-width: 32px;
  flex-shrink: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--text-primary);
  color: var(--bg-surface);
  font-weight: 500;
  font-size: 14px;
}

.account-meta,
.menu-profile-copy,
.nav-label,
.brand-button,
.sidebar-section {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
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
  padding: 10px 14px;
  border-radius: var(--radius-md);
  color: var(--text-primary);
  transition: background-color var(--transition-fast), padding var(--transition-fast);
  cursor: pointer;
  overflow: hidden;
}

.nav-item.icon-only {
  justify-content: center;
  padding: 10px;
}

.nav-item:hover,
.recent-item:hover,
.account-trigger:hover,
.menu-item:hover,
.theme-chip:hover,
.section-link:hover {
  background: var(--bg-surface-hover);
}

.nav-item.current {
  font-weight: 500;
  background: var(--bg-surface-hover);
}

.nav-icon {
  width: 20px;
  height: 20px;
  min-width: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: transform var(--transition-fast) cubic-bezier(0.34, 1.56, 0.64, 1), color var(--transition-fast);
}

.nav-item:hover .nav-icon {
  transform: scale(1.15);
  color: var(--text-primary);
}

.nav-icon :deep(svg) {
  width: 100%;
  height: 100%;
}

.account-meta strong,
.menu-profile-copy strong,
.nav-label {
  display: block;
  font-weight: 400;
  font-size: 0.9rem;
  color: var(--text-primary);
}

.account-meta span,
.menu-profile-copy span {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-label,
.brand-button,
.sidebar-section,
.account-meta {
  transition: max-width var(--transition-slow), opacity var(--transition-slow), margin var(--transition-slow), padding var(--transition-slow);
  max-width: 250px;
  opacity: 1;
  white-space: nowrap;
  overflow: hidden;
}

.sidebar:not(.expanded) .nav-label,
.sidebar:not(.expanded) .brand-button,
.sidebar:not(.expanded) .sidebar-section,
.sidebar:not(.expanded) .account-meta {
  max-width: 0;
  opacity: 0;
  margin: 0;
  padding: 0;
  pointer-events: none;
}

.sidebar-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color-subtle);
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
  padding: 8px 12px;
  text-align: left;
  border-radius: 8px;
  transition: background-color var(--transition-fast), transform var(--transition-fast);
  cursor: pointer;
}

.recent-item:hover {
  transform: translateX(4px);
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
  background: var(--bg-surface-hover);
  font-weight: 500;
}

.account-menu {
  position: fixed;
  left: 16px;
  bottom: 80px;
  width: 260px;
  padding: 8px 0;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-surface-strong);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  z-index: 1000;
}

.menu-email {
  padding: 8px 16px 12px;
  color: var(--text-secondary);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-bottom: 1px solid var(--border-color-subtle);
  margin-bottom: 4px;
}

.menu-group {
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-color-subtle);
}

.menu-group.border-none {
  border-bottom: none;
}

.menu-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 14px;
  color: var(--text-primary);
  background: transparent;
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.menu-item svg {
  color: var(--text-secondary);
  transition: transform var(--transition-fast) cubic-bezier(0.34, 1.56, 0.64, 1), color var(--transition-fast);
}

.menu-item:hover svg {
  transform: scale(1.15);
  color: var(--text-primary);
}

.nav-item:active,
.recent-item:active,
.menu-item:active,
.account-trigger:active,
.section-link:active,
.brand-button:active {
  transform: scale(0.96);
}

.menu-item:hover {
  background: var(--bg-surface-hover);
}

.sidebar-spacer { flex: 1; }

.account-shell { position: relative; width: 100%; }

.account-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  transition: background-color var(--transition-fast);
  cursor: pointer;
}

.account-trigger.active {
  background: var(--bg-surface-hover);
}



.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 24px 28px 18px;
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border-bottom: 1px solid rgba(255, 255, 255, 0.3);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.mobile-menu-btn {
  display: none;
  background: transparent;
  border: none;
  color: var(--text-primary);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  transition: background-color var(--transition-fast);
}

.mobile-menu-btn:active {
  background-color: var(--bg-surface-hover);
}

.topbar h1 {
  margin-top: 4px;
  font-size: clamp(1.1rem, 1vw + 0.95rem, 1.45rem);
  line-height: 1.2;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.theme-chip {
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(12px);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.theme-chip:hover {
  background: rgba(255, 255, 255, 0.6);
  color: var(--text-primary);
}





.content-shell {
  min-width: 0;
  min-height: 100vh;
}

.content-body {
  padding: 32px 32px 64px;
  width: 100%;
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

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 250ms ease, transform 250ms ease;
}
.page-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
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
    z-index: 50;
  }

  .content-shell {
    padding-left: var(--sidebar-collapsed-width);
  }

  .sidebar.expanded + .content-shell {
    padding-left: var(--sidebar-width);
  }
}

.mobile-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  z-index: 40;
  opacity: 0;
  pointer-events: none;
  transition: opacity 300ms;
}

@media (max-width: 768px) {
  .mobile-overlay {
    display: block;
  }

  .mobile-overlay.visible {
    opacity: 1;
    pointer-events: auto;
  }

  .content-shell,
  .sidebar.expanded + .content-shell {
    padding-left: 0;
  }

  .sidebar {
    transform: translateX(-100%);
    width: 280px;
    max-width: 85vw;
  }

  .sidebar.expanded {
    transform: translateX(0);
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.18);
  }

  .mobile-menu-btn {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .topbar {
    padding: 16px 20px 14px;
  }

  .content-body {
    padding: 0 16px 24px;
  }
}
</style>

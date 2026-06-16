import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"
import { useAuthStore } from "@/stores/auth"

import AppLayout from "@/layouts/AppLayout.vue"
import LoginView from "@/views/LoginView.vue"
import ChatView from "@/views/ChatView.vue"
import TasksView from "@/views/TasksView.vue"
import DocumentsView from "@/views/DocumentsView.vue"
import AdminView from "@/views/AdminView.vue"
import SettingsView from "@/views/SettingsView.vue"
import NotFoundView from "@/views/NotFoundView.vue"

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "Login",
    component: LoginView,
    meta: { guest: true, title: "登录" },
  },
  {
    path: "/",
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      { path: "", redirect: "/chat" },
      { path: "chat", name: "Chat", component: ChatView, meta: { title: "智能问答" } },
      { path: "tasks", name: "Tasks", component: TasksView, meta: { title: "任务中心", role: "ADMIN" } },
      { path: "documents", name: "Documents", component: DocumentsView, meta: { title: "文档中心" } },
      { path: "admin", name: "Admin", component: AdminView, meta: { title: "平台管理", role: "ADMIN" } },
      { path: "settings", name: "Settings", component: SettingsView, meta: { title: "个人设置" } },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    name: "NotFound",
    component: NotFoundView,
    meta: { title: "页面不存在" },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  const hasToken = Boolean(authStore.token)
  const title = typeof to.meta.title === "string" ? to.meta.title : ""
  if (title) {
    document.title = `${title} - DocMind`
  }
  if (to.meta.requiresAuth && !hasToken) {
    return next({ name: "Login", query: { redirect: to.fullPath } })
  }
  if (to.meta.guest && hasToken) {
    return next({ name: "Chat" })
  }
  if (to.meta.role && authStore.user && authStore.user.role !== to.meta.role) {
    return next({ name: "Chat" })
  }
  next()
})

export default router

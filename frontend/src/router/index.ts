import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"
import { useAuthStore } from "@/stores/auth"

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "Login",
    component: () => import("@/views/LoginView.vue"),
    meta: { guest: true, title: "登录" },
  },
  {
    path: "/",
    component: () => import("@/layouts/AppLayout.vue"),
    meta: { requiresAuth: true },
    children: [
      { path: "", redirect: "/chat" },
      { path: "chat", name: "Chat", component: () => import("@/views/ChatView.vue"), meta: { title: "智能问答" } },
      { path: "tasks", name: "Tasks", component: () => import("@/views/TasksView.vue"), meta: { title: "任务中心", role: "ADMIN" } },
      { path: "documents", name: "Documents", component: () => import("@/views/DocumentsView.vue"), meta: { title: "文档中心" } },
      { path: "search", name: "Search", component: () => import("@/views/SearchView.vue"), meta: { title: "知识检索" } },
      { path: "admin", name: "Admin", component: () => import("@/views/AdminView.vue"), meta: { title: "平台管理", role: "ADMIN" } },
      { path: "settings", name: "Settings", component: () => import("@/views/SettingsView.vue"), meta: { title: "个人设置" } },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    name: "NotFound",
    component: () => import("@/views/NotFoundView.vue"),
    meta: { title: "页面不存在" },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  const title = typeof to.meta.title === "string" ? to.meta.title : ""
  if (title) {
    document.title = `${title} - DocMind`
  }
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return next({ name: "Login", query: { redirect: to.fullPath } })
  }
  if (to.meta.guest && authStore.isAuthenticated) {
    return next({ name: "Chat" })
  }
  if (to.meta.role && authStore.user?.role !== to.meta.role) {
    return next({ name: "Chat" })
  }
  next()
})

export default router

import { createApp } from "vue"
import { createPinia } from "pinia"
import router from "./router"
import App from "./App.vue"
import "./assets/css/index.css"
import { useAuthStore } from "@/stores/auth"

function setBootMessage(message: string, state: "booting" | "error" | "ready" = "booting") {
  const container = document.getElementById("boot-status")
  const messageNode = document.getElementById("boot-message")
  if (container) {
    container.setAttribute("data-state", state)
  }
  if (messageNode) {
    messageNode.textContent = message
  }
}

window.addEventListener("error", (event) => {
  const detail = event.error?.message || event.message || "未知启动错误"
  console.error("[DocMind] window error", event.error || event.message)
  setBootMessage(`应用启动失败：${detail}\n请重新同步移动端资源后再试。`, "error")
})

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason?.message || String(event.reason || "未知 Promise 错误")
  console.error("[DocMind] unhandled rejection", event.reason)
  setBootMessage(`应用启动失败：${reason}\n请检查移动端网络与构建资源。`, "error")
})

async function bootstrap() {
  setBootMessage("正在初始化应用…")

  const app = createApp(App)
  const pinia = createPinia()
  app.use(pinia)
  app.use(router)

  const authStore = useAuthStore(pinia)
  setBootMessage("正在恢复登录状态…")
  await authStore.hydrateUser()

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && authStore.isAuthenticated) {
      void authStore.hydrateUser()
    }
  })

  window.addEventListener("focus", () => {
    if (authStore.isAuthenticated) {
      void authStore.hydrateUser()
    }
  })

  setBootMessage("正在渲染界面…")
  app.mount("#app")
  setBootMessage("启动完成", "ready")
}

bootstrap().catch((error) => {
  console.error("[DocMind] bootstrap failed", error)
  const detail = error instanceof Error ? error.message : String(error)
  setBootMessage(`应用启动失败：${detail}\n请检查移动端配置或查看日志。`, "error")
})

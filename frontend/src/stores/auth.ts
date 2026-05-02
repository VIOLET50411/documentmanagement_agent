import { defineStore } from "pinia"
import { computed, ref, type Ref } from "vue"
import { authApi, type RegisterPayload, type VerificationCodePayload } from "@/api/auth"
import type { UserPayload } from "@/api/schemas"
import { isNativeApp, platformName } from "@/mobile/capacitor"
import { loginWithMobilePassword } from "@/mobile/auth"
import { heartbeatStoredPushDevice, registerPushDevice, unregisterStoredPushDevice } from "@/mobile/push"
import router from "@/router"

const TOKEN_KEY = "docmind_token"
const REFRESH_TOKEN_KEY = "docmind_refresh_token"
const USER_KEY = "docmind_user"
const PUSH_AUTO_REGISTER_KEY = "docmind_native_push_registered"

function readStoredUser(): UserPayload | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserPayload
  } catch {
    return null
  }
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || "")
  const refreshToken = ref(localStorage.getItem(REFRESH_TOKEN_KEY) || "")
  const user: Ref<UserPayload | null> = ref(readStoredUser())
  const refreshInFlight = ref<Promise<boolean> | null>(null)

  const isAuthenticated = computed(() => !!token.value)

  function shouldUseNativeOAuth() {
    return isNativeApp() && import.meta.env.VITE_NATIVE_MOBILE_OAUTH_ENABLED !== "false"
  }

  async function login(username: string, password: string) {
    const res = shouldUseNativeOAuth()
      ? await loginWithMobilePassword({ username, password })
      : await authApi.login(username, password)
    token.value = res.access_token
    refreshToken.value = res.refresh_token
    localStorage.setItem(TOKEN_KEY, res.access_token)
    localStorage.setItem(REFRESH_TOKEN_KEY, res.refresh_token)
    try {
      user.value = await authApi.me()
    } catch {
      user.value = { username, role: "EMPLOYEE", email_verified: false }
    }
    localStorage.setItem(USER_KEY, JSON.stringify(user.value))
    await ensureNativePushRegistration()
  }

  async function register(data: RegisterPayload) {
    return authApi.register(data)
  }

  async function sendVerificationCode(payload: VerificationCodePayload) {
    return authApi.sendVerificationCode(payload)
  }

  async function requestPasswordReset(email: string) {
    return authApi.requestPasswordReset(email)
  }

  function logout() {
    void unregisterStoredPushDevice().catch(() => undefined)
    token.value = ""
    refreshToken.value = ""
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(PUSH_AUTO_REGISTER_KEY)
    router.push("/login")
  }

  async function hydrateUser() {
    if (!token.value) return
    try {
      user.value = await authApi.me()
      localStorage.setItem(USER_KEY, JSON.stringify(user.value))
      await ensureNativePushRegistration()
    } catch {
      const refreshed = await refreshSession()
      if (!refreshed) {
        logout()
        return
      }
      try {
        user.value = await authApi.me()
        localStorage.setItem(USER_KEY, JSON.stringify(user.value))
        await ensureNativePushRegistration()
      } catch {
        logout()
      }
    }
  }

  async function refreshSession(): Promise<boolean> {
    if (!refreshToken.value) return false
    if (refreshInFlight.value) return refreshInFlight.value

    const pending = (async () => {
      try {
        const res = await authApi.refresh(refreshToken.value)
        token.value = res.access_token
        refreshToken.value = res.refresh_token
        localStorage.setItem(TOKEN_KEY, res.access_token)
        localStorage.setItem(REFRESH_TOKEN_KEY, res.refresh_token)
        return true
      } catch {
        return false
      } finally {
        refreshInFlight.value = null
      }
    })()

    refreshInFlight.value = pending
    return pending
  }

  async function ensureNativePushRegistration() {
    if (!isNativeApp() || !token.value || !user.value) return
    const currentPlatform = platformName()
    const marker = `${currentPlatform}:${user.value.username || user.value.email || "user"}`
    if (localStorage.getItem(PUSH_AUTO_REGISTER_KEY) === marker) {
      try {
        await heartbeatStoredPushDevice()
      } catch {
        localStorage.removeItem(PUSH_AUTO_REGISTER_KEY)
      }
      return
    }
    try {
      const result = await registerPushDevice({
        platform: currentPlatform,
        deviceName: user.value.username
          ? `${user.value.username} 的 ${currentPlatform} 设备`
          : `${currentPlatform} 设备`,
        appVersion: "1.0.0",
      })
      if (result && (result as { registered?: boolean }).registered) {
        localStorage.setItem(PUSH_AUTO_REGISTER_KEY, marker)
      }
    } catch {
      // Push registration failure should not block the main sign-in flow.
    }
  }

  return {
    token,
    refreshToken,
    user,
    isAuthenticated,
    login,
    register,
    sendVerificationCode,
    requestPasswordReset,
    logout,
    hydrateUser,
    refreshSession,
    ensureNativePushRegistration,
  }
})

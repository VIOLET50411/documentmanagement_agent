import { defineStore } from "pinia"
import { computed, ref, type Ref } from "vue"
import { authApi, type RegisterPayload, type VerificationCodePayload } from "@/api/auth"
import type { UserPayload } from "@/api/schemas"
import router from "@/router"

const TOKEN_KEY = "docmind_token"
const REFRESH_TOKEN_KEY = "docmind_refresh_token"
const USER_KEY = "docmind_user"

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

  const isAuthenticated = computed(() => !!token.value)

  async function login(username: string, password: string) {
    const res = await authApi.login(username, password)
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
    token.value = ""
    refreshToken.value = ""
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    router.push("/login")
  }

  async function hydrateUser() {
    if (!token.value) return
    try {
      user.value = await authApi.me()
      localStorage.setItem(USER_KEY, JSON.stringify(user.value))
    } catch {
      logout()
    }
  }

  return { token, refreshToken, user, isAuthenticated, login, register, sendVerificationCode, requestPasswordReset, logout, hydrateUser }
})

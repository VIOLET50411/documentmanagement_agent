import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

const pushMock = vi.fn()
const loginMock = vi.fn()
const loginWithMobilePasswordMock = vi.fn()
const meMock = vi.fn()
const registerMock = vi.fn()
const verifyCodeMock = vi.fn()
const passwordResetMock = vi.fn()
const isNativeAppMock = vi.fn()

vi.mock("@/router", () => ({
  default: {
    push: pushMock,
  },
}))

vi.mock("@/api/auth", () => ({
  authApi: {
    login: loginMock,
    me: meMock,
    register: registerMock,
    sendVerificationCode: verifyCodeMock,
    requestPasswordReset: passwordResetMock,
  },
}))

vi.mock("@/mobile/auth", () => ({
  loginWithMobilePassword: loginWithMobilePasswordMock,
}))

vi.mock("@/mobile/capacitor", () => ({
  isNativeApp: isNativeAppMock,
  platformName: () => "web",
  getApiBaseUrl: () => "/api/v1",
}))

describe("auth store", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    isNativeAppMock.mockReturnValue(false)
  })

  it("stores tokens and current user on login", async () => {
    loginMock.mockResolvedValue({ access_token: "token-1", refresh_token: "refresh-1" })
    meMock.mockResolvedValue({ username: "alice", role: "ADMIN", email_verified: true })

    const { useAuthStore } = await import("../auth")
    const store = useAuthStore()

    await store.login("alice", "Password123")

    expect(store.token).toBe("token-1")
    expect(store.refreshToken).toBe("refresh-1")
    expect(store.user?.username).toBe("alice")
    expect(localStorage.getItem("docmind_token")).toBe("token-1")
  })

  it("falls back to a minimal user profile when /me fails", async () => {
    loginMock.mockResolvedValue({ access_token: "token-2", refresh_token: "refresh-2" })
    meMock.mockRejectedValue(new Error("boom"))

    const { useAuthStore } = await import("../auth")
    const store = useAuthStore()

    await store.login("bob", "Password123")

    expect(store.user).toEqual({ username: "bob", role: "EMPLOYEE", email_verified: false })
  })

  it("clears auth state and routes to login on logout", async () => {
    const { useAuthStore } = await import("../auth")
    const store = useAuthStore()
    store.token = "token-3"
    store.refreshToken = "refresh-3"
    store.user = { username: "carol", role: "EMPLOYEE", email_verified: false }

    store.logout()

    expect(store.token).toBe("")
    expect(store.refreshToken).toBe("")
    expect(store.user).toBeNull()
    expect(pushMock).toHaveBeenCalledWith("/login")
  })
})

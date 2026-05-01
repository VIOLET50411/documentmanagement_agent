import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

const pushToMock = vi.fn()
const loginMock = vi.fn()
const meMock = vi.fn()
const refreshMock = vi.fn()
const registerPushDeviceMock = vi.fn()
const heartbeatStoredPushDeviceMock = vi.fn()
const unregisterStoredPushDeviceMock = vi.fn()
const isNativeAppMock = vi.fn()
const platformNameMock = vi.fn()
const loginWithMobilePasswordMock = vi.fn()

vi.mock("@/api/auth", () => ({
  authApi: {
    login: (...args: unknown[]) => loginMock(...args),
    me: (...args: unknown[]) => meMock(...args),
    refresh: (...args: unknown[]) => refreshMock(...args),
  },
}))

vi.mock("@/mobile/push", () => ({
  registerPushDevice: (...args: unknown[]) => registerPushDeviceMock(...args),
  heartbeatStoredPushDevice: (...args: unknown[]) => heartbeatStoredPushDeviceMock(...args),
  unregisterStoredPushDevice: (...args: unknown[]) => unregisterStoredPushDeviceMock(...args),
}))

vi.mock("@/mobile/auth", () => ({
  loginWithMobilePassword: (...args: unknown[]) => loginWithMobilePasswordMock(...args),
}))

vi.mock("@/mobile/capacitor", () => ({
  isNativeApp: (...args: unknown[]) => isNativeAppMock(...args),
  platformName: (...args: unknown[]) => platformNameMock(...args),
}))

vi.mock("@/router", () => ({
  default: {
    push: (...args: unknown[]) => pushToMock(...args),
  },
}))

describe("auth store", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    isNativeAppMock.mockReturnValue(true)
    platformNameMock.mockReturnValue("android")
  })

  it("registers native push after login", async () => {
    loginWithMobilePasswordMock.mockResolvedValue({
      access_token: "token-1",
      refresh_token: "refresh-1",
    })
    meMock.mockResolvedValue({
      username: "admin_demo",
      email: "admin@example.com",
      role: "ADMIN",
      email_verified: true,
    })
    registerPushDeviceMock.mockResolvedValue({ registered: true, token: "push-token-1" })

    const { useAuthStore } = await import("./auth")
    const store = useAuthStore()

    await store.login("admin_demo", "Password123")

    expect(store.token).toBe("token-1")
    expect(store.refreshToken).toBe("refresh-1")
    expect(loginWithMobilePasswordMock).toHaveBeenCalledWith({
      username: "admin_demo",
      password: "Password123",
    })
    expect(loginMock).not.toHaveBeenCalled()
    expect(registerPushDeviceMock).toHaveBeenCalledTimes(1)
    expect(registerPushDeviceMock).toHaveBeenCalledWith({
      platform: "android",
      deviceName: "admin_demo 的 android 设备",
      appVersion: "1.0.0",
    })
    expect(localStorage.getItem("docmind_native_push_registered")).toBe("android:admin_demo")
  })

  it("uses heartbeat when native push is already registered", async () => {
    localStorage.setItem("docmind_token", "token-2")
    localStorage.setItem("docmind_refresh_token", "refresh-2")
    localStorage.setItem("docmind_native_push_registered", "android:admin_demo")
    meMock.mockResolvedValue({
      username: "admin_demo",
      email: "admin@example.com",
      role: "ADMIN",
      email_verified: true,
    })
    heartbeatStoredPushDeviceMock.mockResolvedValue(true)

    const { useAuthStore } = await import("./auth")
    const store = useAuthStore()

    await store.hydrateUser()

    expect(heartbeatStoredPushDeviceMock).toHaveBeenCalledTimes(1)
    expect(registerPushDeviceMock).not.toHaveBeenCalled()
  })
})

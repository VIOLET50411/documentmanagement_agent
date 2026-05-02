import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

const listDevicesMock = vi.fn()
const summarizeDevicesMock = vi.fn()
const listEventsMock = vi.fn()
const registerDeviceMock = vi.fn()
const unregisterDeviceMock = vi.fn()
const getStoredPushRegistrationMock = vi.fn()
const heartbeatStoredPushDeviceMock = vi.fn()
const registerPushDeviceMock = vi.fn()

vi.mock("@/api/notifications", () => ({
  notificationsApi: {
    listDevices: listDevicesMock,
    summarizeDevices: summarizeDevicesMock,
    listEvents: listEventsMock,
    registerDevice: registerDeviceMock,
    unregisterDevice: unregisterDeviceMock,
  },
}))

vi.mock("@/mobile/capacitor", () => ({
  isNativeApp: () => false,
  platformName: () => "web",
}))

vi.mock("@/mobile/push", () => ({
  getStoredPushRegistration: getStoredPushRegistrationMock,
  heartbeatStoredPushDevice: heartbeatStoredPushDeviceMock,
  registerPushDevice: registerPushDeviceMock,
}))

describe("notifications store", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getStoredPushRegistrationMock.mockReturnValue(null)
    listDevicesMock.mockResolvedValue([])
    summarizeDevicesMock.mockResolvedValue({
      total: 0,
      active: 0,
      inactive: 0,
      by_platform: {},
      current_token_provided: false,
      current_token_status: "not_provided",
    })
    listEventsMock.mockResolvedValue({ items: [] })
  })

  it("loads device and event summaries", async () => {
    getStoredPushRegistrationMock.mockReturnValue({ token: "abc123456789", platform: "android" })
    listDevicesMock.mockResolvedValue([{ id: "d1", platform: "android", device_token: "abc123456789", is_active: true }])
    summarizeDevicesMock.mockResolvedValue({
      total: 1,
      active: 1,
      inactive: 0,
      by_platform: { android: { active: 1, inactive: 0, total: 1 } },
      current_token_provided: true,
      current_token_status: "matched_active",
      current_device: { id: "d1", platform: "android", device_token: "abc123456789", is_active: true, updated_at: "2026-05-03T00:00:00Z" },
    })
    listEventsMock.mockResolvedValue({ items: [{ title: "完成", status: "done" }] })

    const { useNotificationsStore } = await import("../notifications")
    const store = useNotificationsStore()

    await store.loadPushData()

    expect(store.devices).toHaveLength(1)
    expect(store.events).toHaveLength(1)
    expect(store.currentTokenStatusLabel).toBe("已匹配并启用")
  })

  it("blocks manual registration when token is empty", async () => {
    const { useNotificationsStore } = await import("../notifications")
    const store = useNotificationsStore()

    store.deviceForm.device_token = "   "
    await store.registerDevice()

    expect(store.deviceMessage).toBe("请先填写设备 token。")
    expect(registerDeviceMock).not.toHaveBeenCalled()
  })

  it("returns a clear message when auto registration is unavailable on web", async () => {
    const { useNotificationsStore } = await import("../notifications")
    const store = useNotificationsStore()

    await store.registerCurrentDevicePush("alice")

    expect(store.nativePushMessage).toBe("当前运行环境不是原生 App，无法自动申请系统推送 token。")
    expect(registerPushDeviceMock).not.toHaveBeenCalled()
  })

  it("sends heartbeat for stored tokens", async () => {
    getStoredPushRegistrationMock.mockReturnValue({ token: "abc123456789", platform: "android" })
    heartbeatStoredPushDeviceMock.mockResolvedValue(true)
    const { useNotificationsStore } = await import("../notifications")
    const store = useNotificationsStore()

    await store.heartbeatCurrentDevicePush()

    expect(heartbeatStoredPushDeviceMock).toHaveBeenCalled()
    expect(store.nativePushMessage).toBe("设备心跳已发送，后端活跃时间已刷新。")
  })
})

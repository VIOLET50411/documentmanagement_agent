import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

const getLLMDomainConfigMock = vi.fn()
const getRuntimeMetricsMock = vi.fn()
const getRetrievalIntegrityMock = vi.fn()
const getSecurityPolicyMock = vi.fn()
const getMobileAuthStatusMock = vi.fn()
const getPushNotificationStatusMock = vi.fn()
const getBackendStatusMock = vi.fn()

vi.mock("@/api/admin", () => ({
  adminApi: {
    getLLMDomainConfig: getLLMDomainConfigMock,
    getRuntimeMetrics: getRuntimeMetricsMock,
    getRetrievalIntegrity: getRetrievalIntegrityMock,
    getSecurityPolicy: getSecurityPolicyMock,
    getMobileAuthStatus: getMobileAuthStatusMock,
    getPushNotificationStatus: getPushNotificationStatusMock,
    getBackendStatus: getBackendStatusMock,
  },
}))

describe("settings store", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it("persists response and notification preferences", async () => {
    const { useSettingsStore } = await import("../settings")
    const store = useSettingsStore()

    store.setResponseStyle("bullets")
    store.setResponseLanguage("en-US")
    store.setNotificationsEnabled(false)
    store.setStatusHintsEnabled(false)

    expect(localStorage.getItem("docmind_response_style")).toBe("bullets")
    expect(localStorage.getItem("docmind_response_language")).toBe("en-US")
    expect(localStorage.getItem("docmind_notifications_enabled")).toBe("false")
    expect(localStorage.getItem("docmind_status_hints_enabled")).toBe("false")
  })

  it("loads admin diagnostics when admin access is allowed", async () => {
    getLLMDomainConfigMock.mockResolvedValue({ enterprise_enabled: true })
    getRuntimeMetricsMock.mockResolvedValue({ summary: { ttft_ms_p95: 123 } })
    getRetrievalIntegrityMock.mockResolvedValue({ healthy: true, score: 100 })
    getSecurityPolicyMock.mockResolvedValue({ mode: "strict" })
    getMobileAuthStatusMock.mockResolvedValue({ enabled: true })
    getPushNotificationStatusMock.mockResolvedValue({ providers: { fcm: { ready: true } } })
    getBackendStatusMock.mockResolvedValue({ llm: { available: true } })

    const { useSettingsStore } = await import("../settings")
    const store = useSettingsStore()

    await store.loadAdminDiagnostics(true)

    expect(store.llmDomainConfig?.enterprise_enabled).toBe(true)
    expect(store.runtimeMetrics?.summary?.ttft_ms_p95).toBe(123)
    expect(store.retrievalIntegrity?.score).toBe(100)
    expect(store.securityPolicy?.mode).toBe("strict")
    expect(store.mobileAuthStatus?.enabled).toBe(true)
    expect(store.pushProviderStatus?.providers?.fcm?.ready).toBe(true)
    expect(store.backendStatus?.llm?.available).toBe(true)
  })

  it("skips diagnostics calls for non-admin users", async () => {
    const { useSettingsStore } = await import("../settings")
    const store = useSettingsStore()

    await store.loadAdminDiagnostics(false)

    expect(getRuntimeMetricsMock).not.toHaveBeenCalled()
    expect(store.llmDomainConfig).toBeNull()
  })

  it("stores a message when admin diagnostics loading fails", async () => {
    getLLMDomainConfigMock.mockRejectedValue(new Error("service unavailable"))

    const { useSettingsStore } = await import("../settings")
    const store = useSettingsStore()

    await expect(store.loadAdminDiagnostics(true)).rejects.toThrow("service unavailable")
    expect(store.adminDiagnosticsMessage).toBe("service unavailable")
  })
})

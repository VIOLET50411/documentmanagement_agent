import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import SettingsAdminPanels from "../SettingsAdminPanels.vue"

function createProps(overrides: Record<string, any> = {}) {
  return {
    section: "runtime",
    isAdmin: true,
    loadingAdminDiagnostics: false,
    adminDiagnosticsMessage: "",
    llmDomainConfig: null,
    runtimeMetrics: {
      summary: {
        ttft_ms_p95: 120,
        completion_ms_p95: 980,
        sse_disconnects: 2,
        fallback_rate: 0.1,
        deny_rate: 0.05,
        avg_tool_calls: 3,
      },
    },
    retrievalIntegrity: null,
    securityPolicy: null,
    mobileAuthStatus: null,
    pushProviderStatus: null,
    backendStatus: {
      llm: { available: true, model_name: "gpt" },
      milvus: { available: true },
      elasticsearch: { available: false, error: "offline" },
    },
    formatPercent: (value?: number | null) => (value == null ? "-" : `${(value * 100).toFixed(1)}%`),
    clearAdminDiagnosticsMessage: vi.fn(),
    loadAdminDiagnostics: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe("SettingsAdminPanels", () => {
  it("shows admin-only empty state for non-admin users", () => {
    const wrapper = mount(SettingsAdminPanels, {
      props: createProps({ isAdmin: false }),
    })

    expect(wrapper.text()).toContain("这部分仅管理员可查看")
  })

  it("renders runtime diagnostics labels in Chinese", () => {
    const wrapper = mount(SettingsAdminPanels, {
      props: createProps(),
    })

    expect(wrapper.text()).toContain("运行指标")
    expect(wrapper.text()).toContain("首字返回")
    expect(wrapper.text()).toContain("后端连通性")
    expect(wrapper.text()).toContain("在线")
    expect(wrapper.text()).toContain("离线")
  })

  it("formats security and mobile diagnostics for display", () => {
    const wrapper = mount(SettingsAdminPanels, {
      props: createProps({
        section: "mobile",
        mobileAuthStatus: {
          enabled: true,
          issuer: "https://login.example.com/oidc",
          pkce_required: true,
        },
        pushProviderStatus: {
          providers: {
            fcm: { ready: false, reason: "missing credentials" },
            wechat: { ready: true, reason: "" },
          },
        },
      }),
    })

    expect(wrapper.text()).toContain("login.example.com/oidc")
    expect(wrapper.text()).toContain("关键配置缺失，通道暂时不可用。")
    expect(wrapper.text()).toContain("订阅消息通道")
  })
})

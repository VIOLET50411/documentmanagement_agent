import { defineStore } from "pinia"
import { ref } from "vue"
import { adminApi } from "@/api/admin"

const RESPONSE_STYLE_KEY = "docmind_response_style"
const RESPONSE_LANGUAGE_KEY = "docmind_response_language"
const NOTIFICATIONS_ENABLED_KEY = "docmind_notifications_enabled"
const STATUS_HINTS_ENABLED_KEY = "docmind_status_hints_enabled"

type ResponseStyle = "direct" | "detailed" | "bullets"
type ResponseLanguage = "zh-CN" | "en-US"
type SectionKey =
  | "general"
  | "account"
  | "preferences"
  | "models"
  | "runtime"
  | "security"
  | "mobile"
  | "devices"
  | "events"

function readBoolean(key: string, fallback: boolean) {
  const raw = localStorage.getItem(key)
  if (raw === null) return fallback
  return raw === "true"
}

export const useSettingsStore = defineStore("settings", () => {
  const activeSection = ref<SectionKey>("general")
  const responseStyle = ref<ResponseStyle>((localStorage.getItem(RESPONSE_STYLE_KEY) as ResponseStyle) || "direct")
  const responseLanguage = ref<ResponseLanguage>((localStorage.getItem(RESPONSE_LANGUAGE_KEY) as ResponseLanguage) || "zh-CN")
  const notificationsEnabled = ref(readBoolean(NOTIFICATIONS_ENABLED_KEY, true))
  const statusHintsEnabled = ref(readBoolean(STATUS_HINTS_ENABLED_KEY, true))

  const loadingAdminDiagnostics = ref(false)
  const adminDiagnosticsMessage = ref("")
  const llmDomainConfig = ref<Record<string, any> | null>(null)
  const runtimeMetrics = ref<Record<string, any> | null>(null)
  const retrievalIntegrity = ref<Record<string, any> | null>(null)
  const securityPolicy = ref<Record<string, any> | null>(null)
  const mobileAuthStatus = ref<Record<string, any> | null>(null)
  const pushProviderStatus = ref<Record<string, any> | null>(null)
  const backendStatus = ref<Record<string, any> | null>(null)

  function setSection(section: SectionKey) {
    activeSection.value = section
  }

  function setResponseStyle(value: ResponseStyle) {
    responseStyle.value = value
    localStorage.setItem(RESPONSE_STYLE_KEY, value)
  }

  function setResponseLanguage(value: ResponseLanguage) {
    responseLanguage.value = value
    localStorage.setItem(RESPONSE_LANGUAGE_KEY, value)
  }

  function setNotificationsEnabled(value: boolean) {
    notificationsEnabled.value = value
    localStorage.setItem(NOTIFICATIONS_ENABLED_KEY, String(value))
  }

  function setStatusHintsEnabled(value: boolean) {
    statusHintsEnabled.value = value
    localStorage.setItem(STATUS_HINTS_ENABLED_KEY, String(value))
  }

  function clearAdminDiagnosticsMessage() {
    adminDiagnosticsMessage.value = ""
  }

  async function loadAdminDiagnostics(isAdmin: boolean) {
    if (!isAdmin) return

    loadingAdminDiagnostics.value = true
    adminDiagnosticsMessage.value = ""
    try {
      const [
        llmDomainResponse,
        runtimeMetricsResponse,
        securityPolicyResponse,
        mobileAuthResponse,
        pushProviderResponse,
        backendStatusResponse,
      ] = await Promise.all([
        adminApi.getLLMDomainConfig(),
        adminApi.getRuntimeMetrics(120),
        adminApi.getSecurityPolicy(),
        adminApi.getMobileAuthStatus(),
        adminApi.getPushNotificationStatus(),
        adminApi.getBackendStatus(),
      ])

      llmDomainConfig.value = llmDomainResponse
      runtimeMetrics.value = runtimeMetricsResponse
      securityPolicy.value = securityPolicyResponse
      mobileAuthStatus.value = mobileAuthResponse
      pushProviderStatus.value = pushProviderResponse
      backendStatus.value = backendStatusResponse
    } catch (error) {
      adminDiagnosticsMessage.value = error instanceof Error ? error.message : "加载管理员诊断信息失败。"
      throw error
    } finally {
      loadingAdminDiagnostics.value = false
    }

    try {
      retrievalIntegrity.value = await adminApi.getRetrievalIntegrity(12)
    } catch {
      adminDiagnosticsMessage.value = "检索完整性采样暂时不可用，其余诊断信息已刷新。"
    }
  }

  return {
    activeSection,
    responseStyle,
    responseLanguage,
    notificationsEnabled,
    statusHintsEnabled,
    loadingAdminDiagnostics,
    adminDiagnosticsMessage,
    llmDomainConfig,
    runtimeMetrics,
    retrievalIntegrity,
    securityPolicy,
    mobileAuthStatus,
    pushProviderStatus,
    backendStatus,
    setSection,
    setResponseStyle,
    setResponseLanguage,
    setNotificationsEnabled,
    setStatusHintsEnabled,
    clearAdminDiagnosticsMessage,
    loadAdminDiagnostics,
  }
})

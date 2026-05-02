import { defineStore } from "pinia"
import { computed, reactive, ref } from "vue"
import { notificationsApi, type PushDevicePayload, type PushDeviceSummary } from "@/api/notifications"
import { isNativeApp, platformName } from "@/mobile/capacitor"
import { getStoredPushRegistration, heartbeatStoredPushDevice, registerPushDevice } from "@/mobile/push"

type PushDeviceRecord = PushDevicePayload & {
  id: string
  tenant_id: string
  user_id: string
  is_active: boolean
  created_at?: string
  updated_at?: string
  last_seen_at?: string
}

type PushEventRecord = {
  document_id?: string
  title?: string
  body?: string
  status?: string
  timestamp?: string
  devices?: Array<Record<string, unknown>>
}

type StoredPushRegistration = {
  token: string
  platform: string
  deviceName?: string
  appVersion?: string
}

function formatDate(value?: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`
}

export const useNotificationsStore = defineStore("notifications", () => {
  const isNativeRuntime = ref(isNativeApp())
  const nativePlatform = ref(platformName())
  const nativePlatformLabel = computed(() =>
    nativePlatform.value === "android" ? "Android" : nativePlatform.value === "ios" ? "iOS" : nativePlatform.value
  )

  const devices = ref<PushDeviceRecord[]>([])
  const events = ref<PushEventRecord[]>([])
  const deviceSummary = ref<PushDeviceSummary | null>(null)
  const loadingDevices = ref(false)
  const loadingEvents = ref(false)
  const loadingSummary = ref(false)
  const registering = ref(false)
  const unregisteringToken = ref("")
  const registeringNativePush = ref(false)
  const heartbeatingNativePush = ref(false)
  const deviceMessage = ref("")
  const nativePushMessage = ref("")
  const storedPushRegistration = ref<StoredPushRegistration | null>(getStoredPushRegistration())

  const deviceForm = reactive<PushDevicePayload>({
    platform: nativePlatform.value === "android" || nativePlatform.value === "ios" ? nativePlatform.value : "android",
    device_token: "",
    device_name: "",
    app_version: "1.0.0",
  })

  const currentTokenStatusLabel = computed(() => {
    const status = deviceSummary.value?.current_token_status || "not_provided"
    const labelMap: Record<string, string> = {
      matched_active: "已匹配并启用",
      matched_inactive: "已匹配但已停用",
      not_found: "本地存在但后端未匹配",
      not_provided: "未提供当前 token",
    }
    return labelMap[status] || status
  })

  const currentTokenStatusDetail = computed(() => {
    const summary = deviceSummary.value
    if (!summary) return "设备状态汇总尚未加载。"
    if (summary.current_token_status === "matched_active" && summary.current_device) {
      return `最近活跃：${formatDate(summary.current_device.last_seen_at || summary.current_device.updated_at)}`
    }
    if (summary.current_token_status === "matched_inactive") {
      return "当前本地 token 已在后端登记，但状态为停用，建议重新绑定或发送心跳。"
    }
    if (summary.current_token_status === "not_found") {
      return "本地 token 尚未在后端登记，建议重新注册当前设备。"
    }
    return "当前设备还没有本地保存的 token。"
  })

  function maskToken(token?: string) {
    if (!token) return "-"
    if (token.length <= 12) return token
    return `${token.slice(0, 6)}...${token.slice(-6)}`
  }

  async function loadDevices() {
    loadingDevices.value = true
    try {
      devices.value = await notificationsApi.listDevices()
      storedPushRegistration.value = getStoredPushRegistration()
    } finally {
      loadingDevices.value = false
    }
  }

  async function loadDeviceSummary() {
    loadingSummary.value = true
    try {
      deviceSummary.value = await notificationsApi.summarizeDevices(storedPushRegistration.value?.token)
    } finally {
      loadingSummary.value = false
    }
  }

  async function loadEvents() {
    loadingEvents.value = true
    try {
      const response = await notificationsApi.listEvents(20)
      events.value = response?.items || []
    } finally {
      loadingEvents.value = false
    }
  }

  async function loadPushData() {
    storedPushRegistration.value = getStoredPushRegistration()
    await Promise.all([loadDevices(), loadDeviceSummary(), loadEvents()])
  }

  async function registerCurrentDevicePush(username?: string) {
    if (!isNativeRuntime.value) {
      nativePushMessage.value = "当前运行环境不是原生 App，无法自动申请系统推送 token。"
      return
    }
    registeringNativePush.value = true
    nativePushMessage.value = ""
    try {
      const result = await registerPushDevice({
        platform: nativePlatform.value,
        deviceName: username ? `${username} 的${nativePlatformLabel.value}设备` : `${nativePlatformLabel.value} 设备`,
        appVersion: deviceForm.app_version || "1.0.0",
      })
      storedPushRegistration.value = getStoredPushRegistration()
      if (result && typeof result === "object" && "token" in result && typeof result.token === "string") {
        deviceForm.platform = nativePlatform.value
        deviceForm.device_token = result.token
        nativePushMessage.value = `当前设备已自动注册，token 已同步到后端：${maskToken(result.token)}`
        await loadPushData()
        return
      }
      nativePushMessage.value = "推送权限未授予，未能获取设备 token。"
    } catch (error: any) {
      nativePushMessage.value = error?.message || error?.response?.data?.detail || "自动注册当前设备失败，请稍后重试。"
    } finally {
      registeringNativePush.value = false
    }
  }

  async function heartbeatCurrentDevicePush() {
    if (!storedPushRegistration.value) {
      nativePushMessage.value = "当前没有本地保存的设备 token，无法发送心跳。"
      return
    }
    heartbeatingNativePush.value = true
    nativePushMessage.value = ""
    try {
      await heartbeatStoredPushDevice()
      nativePushMessage.value = "设备心跳已发送，后端活跃时间已刷新。"
      await loadPushData()
    } catch (error: any) {
      nativePushMessage.value = error?.message || error?.response?.data?.detail || "设备心跳发送失败，请稍后重试。"
    } finally {
      heartbeatingNativePush.value = false
    }
  }

  async function registerDevice() {
    if (!deviceForm.device_token.trim()) {
      deviceMessage.value = "请先填写设备 token。"
      return
    }
    registering.value = true
    deviceMessage.value = ""
    try {
      await notificationsApi.registerDevice({
        platform: deviceForm.platform,
        device_token: deviceForm.device_token.trim(),
        device_name: deviceForm.device_name?.trim() || undefined,
        app_version: deviceForm.app_version?.trim() || undefined,
      })
      deviceMessage.value = "设备登记成功。"
      deviceForm.device_token = ""
      deviceForm.device_name = ""
      await loadPushData()
    } catch (error: any) {
      deviceMessage.value = error?.response?.data?.detail || "设备登记失败，请重试。"
    } finally {
      registering.value = false
    }
  }

  async function unregisterDevice(device: PushDeviceRecord) {
    unregisteringToken.value = device.device_token
    deviceMessage.value = ""
    try {
      await notificationsApi.unregisterDevice({
        platform: device.platform,
        device_token: device.device_token,
      })
      deviceMessage.value = "设备已注销。"
      await loadPushData()
    } catch (error: any) {
      deviceMessage.value = error?.response?.data?.detail || "设备注销失败，请重试。"
    } finally {
      unregisteringToken.value = ""
    }
  }

  return {
    isNativeRuntime,
    nativePlatform,
    nativePlatformLabel,
    devices,
    events,
    deviceSummary,
    loadingDevices,
    loadingEvents,
    loadingSummary,
    registering,
    unregisteringToken,
    registeringNativePush,
    heartbeatingNativePush,
    deviceMessage,
    nativePushMessage,
    storedPushRegistration,
    deviceForm,
    currentTokenStatusLabel,
    currentTokenStatusDetail,
    maskToken,
    loadDevices,
    loadDeviceSummary,
    loadEvents,
    loadPushData,
    registerCurrentDevicePush,
    heartbeatCurrentDevicePush,
    registerDevice,
    unregisterDevice,
  }
})

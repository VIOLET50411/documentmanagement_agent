import { apiDelete, apiGet, apiPost } from "./http"

export type PushDevicePayload = {
  platform: string
  device_token: string
  device_name?: string
  app_version?: string
}

export type PushDeviceHeartbeatPayload = {
  device_token: string
  app_version?: string
}

export type PushTestPayload = {
  title?: string
  body?: string
}

export type PushDeviceSummary = {
  total: number
  active: number
  inactive: number
  by_platform: Record<string, { active: number; inactive: number; total: number }>
  current_token_provided: boolean
  current_token_status: "matched_active" | "matched_inactive" | "not_found" | "not_provided"
  current_device?: {
    id: string
    platform: string
    device_token: string
    device_name?: string
    app_version?: string
    is_active: boolean
    updated_at?: string
    last_seen_at?: string
  } | null
}

export const notificationsApi = {
  listDevices() {
    return apiGet("/notifications/devices")
  },

  summarizeDevices(currentToken?: string) {
    return apiGet<PushDeviceSummary>("/notifications/devices/summary", {
      params: currentToken ? { current_token: currentToken } : {},
    })
  },

  listEvents(limit = 20) {
    return apiGet("/notifications/events", { params: { limit } })
  },

  registerDevice(payload: PushDevicePayload) {
    return apiPost("/notifications/devices", payload)
  },

  heartbeatDevice(payload: PushDeviceHeartbeatPayload) {
    return apiPost("/notifications/devices/heartbeat", payload)
  },

  sendTest(payload: PushTestPayload = {}) {
    return apiPost("/notifications/test", payload)
  },

  unregisterDevice(payload: PushDevicePayload) {
    return apiDelete("/notifications/devices", { data: payload })
  },
}

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

export const notificationsApi = {
  listDevices() {
    return apiGet("/notifications/devices")
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

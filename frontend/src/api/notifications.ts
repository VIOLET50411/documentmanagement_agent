import { apiDelete, apiGet, apiPost } from "./http"

export type PushDevicePayload = {
  platform: string
  device_token: string
  device_name?: string
  app_version?: string
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

  unregisterDevice(payload: PushDevicePayload) {
    return apiDelete("/notifications/devices", { data: payload })
  },
}

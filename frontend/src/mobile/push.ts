import { PushNotifications } from "@capacitor/push-notifications"
import { notificationsApi } from "@/api/notifications"

const PUSH_TOKEN_KEY = "docmind_native_push_token"
const PUSH_PLATFORM_KEY = "docmind_native_push_platform"
const PUSH_DEVICE_NAME_KEY = "docmind_native_push_device_name"
const PUSH_APP_VERSION_KEY = "docmind_native_push_app_version"

type RegisterOptions = {
  platform: string
  deviceName?: string
  appVersion?: string
}

type StoredPushRegistration = {
  token: string
  platform: string
  deviceName?: string
  appVersion?: string
}

function savePushRegistration(token: string, options: RegisterOptions) {
  localStorage.setItem(PUSH_TOKEN_KEY, token)
  localStorage.setItem(PUSH_PLATFORM_KEY, options.platform)
  if (options.deviceName) {
    localStorage.setItem(PUSH_DEVICE_NAME_KEY, options.deviceName)
  }
  if (options.appVersion) {
    localStorage.setItem(PUSH_APP_VERSION_KEY, options.appVersion)
  }
}

export function getStoredPushRegistration(): StoredPushRegistration | null {
  const token = localStorage.getItem(PUSH_TOKEN_KEY) || ""
  const platform = localStorage.getItem(PUSH_PLATFORM_KEY) || ""
  const deviceName = localStorage.getItem(PUSH_DEVICE_NAME_KEY) || ""
  const appVersion = localStorage.getItem(PUSH_APP_VERSION_KEY) || ""
  if (!token || !platform) {
    return null
  }
  return {
    token,
    platform,
    deviceName: deviceName || undefined,
    appVersion: appVersion || undefined,
  }
}

export async function registerPushDevice(options: RegisterOptions) {
  const permission = await PushNotifications.requestPermissions()
  if (permission.receive !== "granted") {
    return { registered: false, reason: "permission_denied" }
  }

  await PushNotifications.register()

  return new Promise((resolve, reject) => {
    let registrationHandle: Awaited<ReturnType<typeof PushNotifications.addListener>> | null = null
    let registrationErrorHandle: Awaited<ReturnType<typeof PushNotifications.addListener>> | null = null

    const cleanup = async () => {
      await registrationHandle?.remove()
      await registrationErrorHandle?.remove()
    }

    PushNotifications.addListener("registration", async (token) => {
      try {
        await notificationsApi.registerDevice({
          platform: options.platform,
          device_token: token.value,
          device_name: options.deviceName,
          app_version: options.appVersion,
        })
        savePushRegistration(token.value, options)
        resolve({ registered: true, token: token.value })
      } catch (error) {
        reject(error)
      } finally {
        await cleanup()
      }
    }).then((handle) => {
      registrationHandle = handle
    })

    PushNotifications.addListener("registrationError", async (error) => {
      await cleanup()
      reject(error)
    }).then((handle) => {
      registrationErrorHandle = handle
    })
  })
}

export async function heartbeatStoredPushDevice() {
  const current = getStoredPushRegistration()
  if (!current) return false
  await notificationsApi.heartbeatDevice({
    device_token: current.token,
    app_version: current.appVersion,
  })
  return true
}

export async function unregisterStoredPushDevice() {
  const current = getStoredPushRegistration()
  if (!current) return false
  try {
    await notificationsApi.unregisterDevice({
      platform: current.platform,
      device_token: current.token,
      device_name: current.deviceName,
      app_version: current.appVersion,
    })
  } finally {
    localStorage.removeItem(PUSH_TOKEN_KEY)
    localStorage.removeItem(PUSH_PLATFORM_KEY)
    localStorage.removeItem(PUSH_DEVICE_NAME_KEY)
    localStorage.removeItem(PUSH_APP_VERSION_KEY)
  }
  return true
}

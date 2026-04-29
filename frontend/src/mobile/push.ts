import { PushNotifications } from "@capacitor/push-notifications"
import { notificationsApi } from "@/api/notifications"

type RegisterOptions = {
  platform: string
  deviceName?: string
  appVersion?: string
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

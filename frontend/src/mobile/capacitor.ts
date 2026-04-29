import { Capacitor } from "@capacitor/core"

export function isNativeApp() {
  return Capacitor.isNativePlatform()
}

export function platformName() {
  return Capacitor.getPlatform()
}

const nativeApiBase = "http://172.20.10.3:18000/api/v1"

export function getApiBaseUrl() {
  return isNativeApp() ? nativeApiBase : "/api/v1"
}

export function getAbsoluteApiBaseUrl() {
  return isNativeApp() ? nativeApiBase : (import.meta.env.VITE_API_BASE_URL || "") + "/api/v1"
}

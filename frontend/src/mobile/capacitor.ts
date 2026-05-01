import { Capacitor } from "@capacitor/core"

export function isNativeApp() {
  return Capacitor.isNativePlatform()
}

export function platformName() {
  return Capacitor.getPlatform()
}

function resolveNativeApiBase() {
  const configured = (import.meta.env.VITE_NATIVE_API_BASE_URL || "").trim()
  if (configured) {
    return configured.replace(/\/$/, "") + "/api/v1"
  }
  // Android 模拟器访问宿主机默认使用 10.0.2.2，避免把临时局域网 IP 写死在代码里。
  return "http://10.0.2.2:18000/api/v1"
}

const nativeApiBase = resolveNativeApiBase()

export function getApiBaseUrl() {
  return isNativeApp() ? nativeApiBase : "/api/v1"
}

export function getAbsoluteApiBaseUrl() {
  return isNativeApp() ? nativeApiBase : (import.meta.env.VITE_API_BASE_URL || "") + "/api/v1"
}

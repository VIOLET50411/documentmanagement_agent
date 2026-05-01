import { Browser } from "@capacitor/browser"
import { apiGet, apiPost } from "@/api/http"
import { platformName } from "@/mobile/capacitor"

export type MobileAuthorizePayload = {
  username: string
  password: string
  client_id: string
  redirect_uri: string
  code_challenge: string
  code_challenge_method?: "S256" | "plain"
  scope?: string
  state?: string
}

export type MobileTokenPayload = {
  code: string
  client_id: string
  redirect_uri: string
  code_verifier: string
}

export type MobileRefreshPayload = {
  refresh_token: string
  client_id: string
}

export type MobilePkceBundle = {
  verifier: string
  challenge: string
  method: "S256"
}

export type MobileAuthConfig = {
  clientId: string
  redirectUri: string
  scope: string
}

export type MobilePasswordLoginPayload = {
  username: string
  password: string
  clientId?: string
  redirectUri?: string
  scope?: string
  state?: string
}

const DEFAULT_SCOPE = "openid profile email offline_access"
const DEFAULT_CAPACITOR_CLIENT_ID = "docmind-capacitor"
const DEFAULT_MINIAPP_CLIENT_ID = "docmind-miniapp"
const DEFAULT_CAPACITOR_REDIRECT_URI = "docmind://auth/callback"
const DEFAULT_MINIAPP_REDIRECT_URI = "https://servicewechat.com/docmind/callback"

export const mobileAuthApi = {
  discovery() {
    return apiGet("/auth/mobile/.well-known/openid-configuration")
  },

  authorize(payload: MobileAuthorizePayload) {
    return apiPost("/auth/mobile/authorize", payload)
  },

  exchangeToken(payload: MobileTokenPayload) {
    return apiPost("/auth/mobile/token", { grant_type: "authorization_code", ...payload })
  },

  refreshToken(payload: MobileRefreshPayload) {
    return apiPost("/auth/mobile/token", { grant_type: "refresh_token", ...payload })
  },

  userinfo() {
    return apiGet("/auth/mobile/userinfo")
  },
}

function currentMobilePlatform() {
  const current = platformName()
  return current === "ios" || current === "android" ? "capacitor" : current
}

export function resolveMobileAuthConfig(overrides: Partial<MobileAuthConfig> = {}): MobileAuthConfig {
  const currentPlatform = currentMobilePlatform()
  const envClientId =
    currentPlatform === "wechat"
      ? (import.meta.env.VITE_MOBILE_WECHAT_CLIENT_ID || "").trim()
      : (import.meta.env.VITE_MOBILE_OAUTH_CLIENT_ID || "").trim()
  const envRedirectUri =
    currentPlatform === "wechat"
      ? (import.meta.env.VITE_MOBILE_WECHAT_REDIRECT_URI || "").trim()
      : (import.meta.env.VITE_MOBILE_OAUTH_REDIRECT_URI || "").trim()

  return {
    clientId:
      overrides.clientId ||
      envClientId ||
      (currentPlatform === "wechat" ? DEFAULT_MINIAPP_CLIENT_ID : DEFAULT_CAPACITOR_CLIENT_ID),
    redirectUri:
      overrides.redirectUri ||
      envRedirectUri ||
      (currentPlatform === "wechat" ? DEFAULT_MINIAPP_REDIRECT_URI : DEFAULT_CAPACITOR_REDIRECT_URI),
    scope: overrides.scope || DEFAULT_SCOPE,
  }
}

function randomBytes(size: number) {
  const bytes = new Uint8Array(size)
  crypto.getRandomValues(bytes)
  return bytes
}

function toBase64Url(bytes: Uint8Array) {
  let binary = ""
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "")
}

async function sha256Base64Url(input: string) {
  const buffer = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input))
  return toBase64Url(new Uint8Array(buffer))
}

export async function generatePkceBundle(): Promise<MobilePkceBundle> {
  const verifier = toBase64Url(randomBytes(32))
  return {
    verifier,
    challenge: await sha256Base64Url(verifier),
    method: "S256",
  }
}

export async function loginWithMobilePassword(payload: MobilePasswordLoginPayload) {
  const config = resolveMobileAuthConfig({
    clientId: payload.clientId,
    redirectUri: payload.redirectUri,
    scope: payload.scope,
  })
  const pkce = await generatePkceBundle()
  const authorization = await mobileAuthApi.authorize({
    username: payload.username,
    password: payload.password,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    code_challenge: pkce.challenge,
    code_challenge_method: pkce.method,
    scope: config.scope,
    state: payload.state,
  })
  const tokens = await mobileAuthApi.exchangeToken({
    code: authorization.code,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    code_verifier: pkce.verifier,
  })
  return {
    ...tokens,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    code_verifier: pkce.verifier,
  }
}

export async function refreshMobileSession(refreshToken: string, clientId?: string) {
  const config = resolveMobileAuthConfig({ clientId })
  const tokens = await mobileAuthApi.refreshToken({
    refresh_token: refreshToken,
    client_id: config.clientId,
  })
  return {
    ...tokens,
    client_id: config.clientId,
  }
}

export async function openSystemAuth(url: string) {
  await Browser.open({ url, presentationStyle: "fullscreen" })
}

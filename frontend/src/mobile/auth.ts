import { Browser } from "@capacitor/browser"
import { apiGet, apiPost } from "@/api/http"

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

  userinfo() {
    return apiGet("/auth/mobile/userinfo")
  },
}

export async function openSystemAuth(url: string) {
  await Browser.open({ url, presentationStyle: "fullscreen" })
}

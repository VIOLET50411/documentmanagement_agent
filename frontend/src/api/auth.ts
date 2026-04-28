import { apiGet, apiPost } from "./http"
import { loginResponseSchema, userSchema, type LoginResponse, type UserPayload } from "./schemas"

export interface RegisterPayload {
  username: string
  email: string
  password: string
  tenant_id?: string
  department?: string
  verification_code?: string
}

export interface VerificationCodePayload {
  email: string
  username?: string
}

export const authApi = {
  async login(username: string, password: string): Promise<LoginResponse> {
    return loginResponseSchema.parse(await apiPost<LoginResponse>("/auth/login", { username, password }))
  },

  register(data: RegisterPayload) {
    return apiPost("/auth/register", data)
  },

  refresh(refreshToken: string) {
    return apiPost<LoginResponse>("/auth/refresh", { refresh_token: refreshToken })
  },

  async me(): Promise<UserPayload> {
    return userSchema.parse(await apiGet<UserPayload>("/auth/me"))
  },

  sendVerificationCode(data: VerificationCodePayload) {
    return apiPost("/auth/send-verification-code", data)
  },

  verifyEmail(data: { email: string; code: string }) {
    return apiPost("/auth/verify-email", data)
  },

  requestPasswordReset(email: string) {
    return apiPost("/auth/password-reset/request", { email })
  },
}

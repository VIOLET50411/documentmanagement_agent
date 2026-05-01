import { beforeEach, describe, expect, it, vi } from "vitest"

const apiGetMock = vi.fn()
const apiPostMock = vi.fn()
const platformNameMock = vi.fn()

vi.mock("@/api/http", () => ({
  apiGet: (...args: unknown[]) => apiGetMock(...args),
  apiPost: (...args: unknown[]) => apiPostMock(...args),
}))

vi.mock("@/mobile/capacitor", () => ({
  platformName: (...args: unknown[]) => platformNameMock(...args),
}))

describe("mobile auth helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    platformNameMock.mockReturnValue("android")
  })

  it("resolves default capacitor oauth config", async () => {
    const { resolveMobileAuthConfig } = await import("./auth")
    expect(resolveMobileAuthConfig()).toEqual({
      clientId: "docmind-capacitor",
      redirectUri: "docmind://auth/callback",
      scope: "openid profile email offline_access",
    })
  })

  it("resolves wechat oauth config when platform is wechat", async () => {
    platformNameMock.mockReturnValue("wechat")
    const { resolveMobileAuthConfig } = await import("./auth")
    expect(resolveMobileAuthConfig()).toEqual({
      clientId: "docmind-miniapp",
      redirectUri: "https://servicewechat.com/docmind/callback",
      scope: "openid profile email offline_access",
    })
  })

  it("generates a valid pkce bundle", async () => {
    const { generatePkceBundle } = await import("./auth")
    const bundle = await generatePkceBundle()

    expect(bundle.method).toBe("S256")
    expect(bundle.verifier.length).toBeGreaterThan(20)
    expect(bundle.challenge.length).toBeGreaterThan(20)
    expect(bundle.verifier).not.toContain("=")
    expect(bundle.challenge).not.toContain("=")
  })

  it("completes mobile password oauth exchange", async () => {
    apiPostMock
      .mockResolvedValueOnce({
        code: "auth-code-1",
        redirect_uri: "docmind://auth/callback",
        expires_at: "2026-05-01T12:00:00Z",
      })
      .mockResolvedValueOnce({
        access_token: "access-1",
        refresh_token: "refresh-1",
        id_token: "id-1",
        token_type: "bearer",
        scope: "openid profile email offline_access",
      })

    const { loginWithMobilePassword } = await import("./auth")
    const result = await loginWithMobilePassword({
      username: "admin_demo",
      password: "Password123",
      state: "state-1",
    })

    expect(apiPostMock).toHaveBeenCalledTimes(2)
    expect(apiPostMock.mock.calls[0][0]).toBe("/auth/mobile/authorize")
    expect(apiPostMock.mock.calls[0][1]).toMatchObject({
      username: "admin_demo",
      password: "Password123",
      client_id: "docmind-capacitor",
      redirect_uri: "docmind://auth/callback",
      code_challenge_method: "S256",
      scope: "openid profile email offline_access",
      state: "state-1",
    })
    expect(apiPostMock.mock.calls[0][1].code_challenge).toBeTruthy()
    expect(apiPostMock.mock.calls[1]).toEqual([
      "/auth/mobile/token",
      {
        grant_type: "authorization_code",
        code: "auth-code-1",
        client_id: "docmind-capacitor",
        redirect_uri: "docmind://auth/callback",
        code_verifier: expect.any(String),
      },
    ])
    expect(result).toMatchObject({
      access_token: "access-1",
      refresh_token: "refresh-1",
      id_token: "id-1",
      client_id: "docmind-capacitor",
      redirect_uri: "docmind://auth/callback",
    })
  })

  it("refreshes mobile session with resolved client id", async () => {
    apiPostMock.mockResolvedValueOnce({
      access_token: "access-2",
      refresh_token: "refresh-2",
      id_token: "id-2",
      token_type: "bearer",
      scope: "openid profile email offline_access",
    })

    const { refreshMobileSession } = await import("./auth")
    const result = await refreshMobileSession("refresh-2")

    expect(apiPostMock).toHaveBeenCalledWith("/auth/mobile/token", {
      grant_type: "refresh_token",
      refresh_token: "refresh-2",
      client_id: "docmind-capacitor",
    })
    expect(result.client_id).toBe("docmind-capacitor")
  })
})

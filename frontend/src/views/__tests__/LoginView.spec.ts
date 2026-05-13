import { describe, expect, it, vi, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"
import { nextTick } from "vue"
import LoginView from "../LoginView.vue"

const pushMock = vi.fn()
const loginMock = vi.fn()
const registerMock = vi.fn()
const resetMock = vi.fn()
const sendVerificationCodeMock = vi.fn()

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}))

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    login: loginMock,
    register: registerMock,
    requestPasswordReset: resetMock,
    sendVerificationCode: sendVerificationCodeMock,
  }),
}))

describe("LoginView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders platform logo and subtitle", () => {
    const wrapper = mount(LoginView)

    expect(wrapper.get("img.login-logo").attributes("src")).toBeTruthy()
    expect(wrapper.text()).toContain("企业文档管理与智能问答平台")
  })

  it("shows validation feedback through StatusMessage", async () => {
    const wrapper = mount(LoginView)

    await wrapper.get("form").trigger("submit.prevent")
    await nextTick()

    expect(wrapper.text()).toContain("用户名不能为空")
    expect(loginMock).not.toHaveBeenCalled()
  })

  it("submits login and routes to chat", async () => {
    loginMock.mockResolvedValue(undefined)
    const wrapper = mount(LoginView)

    await wrapper.get("#username").setValue("admin_demo")
    await wrapper.get("#password").setValue("Password123")
    await wrapper.get("form").trigger("submit.prevent")

    expect(loginMock).toHaveBeenCalledWith("admin_demo", "Password123")
    expect(pushMock).toHaveBeenCalledWith("/chat")
  })
})

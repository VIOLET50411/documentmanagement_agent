import { describe, expect, it, vi } from "vitest"
import { shallowMount } from "@vue/test-utils"
import AdminLayout from "../AdminLayout.vue"

const pushMock = vi.fn()
const routeState = {
  query: {},
}

vi.mock("vue-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("vue-router")>()
  return {
    ...actual,
    useRoute: () => routeState,
    useRouter: () => ({
      push: pushMock,
    }),
  }
})

describe("AdminLayout", () => {
  it("renders cleaned tab labels", () => {
    const wrapper = shallowMount(AdminLayout, {
      global: {
        stubs: {
          KeepAlive: { template: "<div><slot /></div>" },
        },
      },
    })

    expect(wrapper.text()).toContain("总览")
    expect(wrapper.text()).toContain("用户管理")
    expect(wrapper.text()).toContain("数据管线")
    expect(wrapper.text()).toContain("检查报告")
  })
})

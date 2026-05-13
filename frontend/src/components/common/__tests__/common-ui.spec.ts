import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import EmptyState from "../EmptyState.vue"
import StatusMessage from "../StatusMessage.vue"

describe("common ui components", () => {
  it("renders EmptyState content and emits action", async () => {
    const wrapper = mount(EmptyState, {
      props: {
        title: "暂无数据",
        description: "请先添加一条记录。",
        actionLabel: "立即添加",
      },
    })

    expect(wrapper.text()).toContain("暂无数据")
    expect(wrapper.text()).toContain("请先添加一条记录。")

    await wrapper.get("button").trigger("click")
    expect(wrapper.emitted("action")).toHaveLength(1)
  })

  it("renders StatusMessage actions and emits dismiss", async () => {
    const wrapper = mount(StatusMessage, {
      props: {
        title: "加载失败",
        message: "请稍后重试",
        tone: "error",
        dismissible: true,
        actionLabel: "重新加载",
      },
    })

    expect(wrapper.attributes("data-tone")).toBe("error")
    expect(wrapper.text()).toContain("加载失败")
    expect(wrapper.text()).toContain("请稍后重试")

    const buttons = wrapper.findAll("button")
    await buttons[0].trigger("click")
    await buttons[1].trigger("click")

    expect(wrapper.emitted("dismiss")).toHaveLength(1)
    expect(wrapper.emitted("action")).toHaveLength(1)
  })
})

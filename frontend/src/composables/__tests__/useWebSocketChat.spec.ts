import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"
import { defineComponent } from "vue"
import { mount } from "@vue/test-utils"
import { useChatStore } from "@/stores/chat"
import { useWebSocketChat } from "../useWebSocketChat"

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static OPEN = 1

  url: string
  readyState = MockWebSocket.OPEN
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: ((error: unknown) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(payload: string) {
    this.sent.push(payload)
  }

  close(code = 1000) {
    this.onclose?.({ code })
  }

  emitOpen() {
    this.onopen?.()
  }

  emitMessage(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

describe("useWebSocketChat", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket)
    MockWebSocket.instances = []
  })

  it("authenticates, sends a message, and updates assistant state from stream events", async () => {
    const chatStore = useChatStore()
    chatStore.createSession()

    const Harness = defineComponent({
      setup(_, { expose }) {
        const runtime = useWebSocketChat()
        expose(runtime)
        return () => null
      },
    })
    const wrapper = mount(Harness)
    const runtime = wrapper.vm.$.exposed as ReturnType<typeof useWebSocketChat>

    const pending = runtime.connect("token-123")
    const socket = MockWebSocket.instances[0]

    expect(socket.url).toContain("/api/v1/ws/chat")

    socket.emitOpen()
    expect(socket.sent[0]).toBe(JSON.stringify({ type: "auth", token: "token-123" }))

    socket.emitMessage({ type: "auth_ok" })
    await pending

    expect(runtime.isConnected.value).toBe(true)

    runtime.sendMessage("请总结这份制度文件")
    expect(chatStore.messages).toHaveLength(2)
    expect(chatStore.messages[0].role).toBe("user")
    expect(chatStore.messages[1].role).toBe("assistant")
    expect(chatStore.streamStatus).toBe("thinking")
    expect(chatStore.streamStatusMsg).toBe("正在理解您的问题...")

    expect(socket.sent[1]).toContain('"type":"message"')

    socket.emitMessage({ type: "status", status: "searching", msg: "正在检索相关文档..." })
    expect(chatStore.streamStatus).toBe("searching")
    expect(chatStore.streamStatusMsg).toBe("正在检索相关文档...")

    socket.emitMessage({ type: "token", content: "第一段答案" })
    expect(chatStore.messages[1].content).toBe("第一段答案")
    expect(chatStore.streamStatus).toBe("streaming")

    socket.emitMessage({
      type: "done",
      answer: "第一段答案",
      citations: [{ doc_id: "doc-1", title: "制度文件" }],
      message_id: "assistant-1",
    })

    expect(chatStore.streamStatus).toBe("done")
    expect(chatStore.messages[1].id).toBe("assistant-1")
    expect(chatStore.messages[1].citations).toHaveLength(1)

    wrapper.unmount()
  })
})

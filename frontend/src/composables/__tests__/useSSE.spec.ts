import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"
import { useChatStore } from "@/stores/chat"

const { streamChatMock } = vi.hoisted(() => ({
  streamChatMock: vi.fn(),
}))

vi.mock("@/api/chat", () => ({
  chatApi: {
    streamChat: streamChatMock,
  },
}))

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

describe("useSSE", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("updates chat state from SSE status, token, and done events", async () => {
    const { useSSE } = await import("../useSSE")
    const chatStore = useChatStore()

    streamChatMock.mockResolvedValue({
      ok: true,
      body: streamFromChunks([
        'data: {"status":"thinking","msg":"正在理解您的问题..."}\n\n',
        'data: {"status":"streaming","token":"你好"}\n\n',
        'data: {"status":"done","message_id":"m-1","thread_id":"t-1","citations":[{"doc_id":"d-1"}]}\n\n',
      ]),
    })

    const runtime = useSSE()
    await runtime.sendMessage("测试消息")

    expect(chatStore.messages).toHaveLength(2)
    expect(chatStore.messages[0].content).toBe("测试消息")
    expect(chatStore.messages[1].content).toBe("你好")
    expect(chatStore.streamStatus).toBe("done")
    expect(chatStore.activeSessionId).toBe("t-1")
    expect(chatStore.messages[1].id).toBe("m-1")
  })

  it("records failure state when SSE request fails", async () => {
    const { useSSE } = await import("../useSSE")
    const chatStore = useChatStore()

    streamChatMock.mockRejectedValue(new Error("network down"))

    const runtime = useSSE()
    await runtime.sendMessage("失败消息")

    expect(runtime.error.value).toBe("network down")
    expect(chatStore.streamStatus).toBe("error")
    expect(chatStore.messages[1].content).toBe("请求失败，请稍后重试。")
  })
})

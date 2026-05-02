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
        'id: trace-1:1\ndata: {"status":"thinking","msg":"正在理解您的问题..."}\n\n',
        'id: trace-1:2\ndata: {"status":"streaming","content":"正在生成回答..."}\n\n',
        'id: trace-1:3\ndata: {"status":"streaming","token":"你"}\n\n',
        'id: trace-1:4\ndata: {"status":"streaming","token":"好"}\n\n',
        'id: trace-1:5\ndata: {"status":"done","message_id":"m-1","thread_id":"t-1","citations":[{"doc_id":"d-1"}]}\n\n',
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

  it("captures runtime metadata for tool call and degraded events", async () => {
    const { useSSE } = await import("../useSSE")
    const chatStore = useChatStore()

    streamChatMock.mockResolvedValue({
      ok: true,
      body: streamFromChunks([
        'id: trace-a:1\ndata: {"status":"tool_call","msg":"正在调用 retrieval.search","sequence_num":1,"trace_id":"trace-a","source":"agent_runtime_v2","degraded":true,"fallback_reason":"partial_backend_failure"}\n\n',
        'id: trace-a:2\ndata: {"status":"error","msg":"检索阶段已降级","sequence_num":2,"trace_id":"trace-a","source":"agent_runtime_v2","degraded":true,"fallback_reason":"partial_backend_failure"}\n\n',
      ]),
    })

    const runtime = useSSE()
    await runtime.sendMessage("测试工具调用")

    expect(chatStore.runtimeEvents).toHaveLength(2)
    expect(chatStore.runtimeEvents[0].status).toBe("tool_call")
    expect(chatStore.runtimeEvents[0].traceId).toBe("trace-a")
    expect(chatStore.runtimeEvents[0].source).toBe("agent_runtime_v2")
    expect(chatStore.runtimeEvents[0].degraded).toBe(true)
    expect(chatStore.runtimeEvents[0].fallbackReason).toBe("partial_backend_failure")
    expect(chatStore.runtimeEvents[1].status).toBe("error")
  })

  it("uses done answer as fallback when no token stream is present", async () => {
    const { useSSE } = await import("../useSSE")
    const chatStore = useChatStore()

    streamChatMock.mockResolvedValue({
      ok: true,
      body: streamFromChunks([
        'id: trace-2:1\ndata: {"status":"thinking","msg":"正在理解您的问题..."}\n\n',
        'id: trace-2:2\ndata: {"status":"done","answer":"最终回答","message_id":"m-2","thread_id":"t-2","citations":[{"doc_id":"d-2"}]}\n\n',
      ]),
    })

    const runtime = useSSE()
    await runtime.sendMessage("只看最终答案")

    expect(chatStore.messages[1].content).toBe("最终回答")
    expect(chatStore.messages[1].citations).toEqual([{ doc_id: "d-2" }])
    expect(chatStore.activeSessionId).toBe("t-2")
    expect(chatStore.streamStatus).toBe("done")
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

import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

const getHistoryMock = vi.fn()

vi.mock("@/api/chat", () => ({
  chatApi: {
    getHistory: getHistoryMock,
  },
}))

describe("chat store", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("creates a new session and activates it", async () => {
    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    const session = store.createSession()

    expect(store.activeSessionId).toBe(session.id)
    expect(store.sessions[0].title).toBe("新对话")
    expect(store.messages).toEqual([])
  })

  it("hydrates session history into message list", async () => {
    getHistoryMock.mockResolvedValue({
      messages: [
        {
          id: "m1",
          role: "assistant",
          content: "已恢复历史",
          citations: [{ doc_id: "d1" }],
          created_at: "2026-04-25T10:00:00Z",
        },
      ],
    })

    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    await store.setActiveSession("thread-1")

    expect(store.activeSessionId).toBe("thread-1")
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].content).toBe("已恢复历史")
  })

  it("tracks stream status and updates the last assistant message", async () => {
    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    store.addMessage({ role: "assistant", content: "前缀", citations: [] })
    store.updateLastAssistantMessage(" + 增量")
    store.setStreamState("streaming", "正在生成")

    expect(store.messages[0].content).toBe("前缀 + 增量")
    expect(store.isStreaming).toBe(true)
    expect(store.streamStatusMsg).toBe("正在生成")
  })

  it("records runtime events for non-streaming phases and deduplicates consecutive events", async () => {
    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    store.setStreamState("thinking", "正在理解问题")
    store.setStreamState("thinking", "正在理解问题")
    store.setStreamState("searching", "正在检索知识库")

    expect(store.runtimeEvents).toHaveLength(2)
    expect(store.runtimeEvents[0].status).toBe("thinking")
    expect(store.runtimeEvents[1].status).toBe("searching")
  })

  it("clears runtime events when a new user message starts", async () => {
    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    store.setStreamState("thinking", "正在理解问题")
    store.addMessage({ role: "user", content: "新的问题", citations: [] })

    expect(store.runtimeEvents).toEqual([])
  })
})

import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

const getHistoryMock = vi.fn()
const getSessionsMock = vi.fn()
const deleteSessionMock = vi.fn()

vi.mock("@/api/chat", () => ({
  chatApi: {
    getHistory: getHistoryMock,
    getSessions: getSessionsMock,
    deleteSession: deleteSessionMock,
  },
}))

describe("chat store", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    window.localStorage.clear()
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

  it("loads recent sessions on initialize and restores the stored active thread without forcing history by default", async () => {
    window.localStorage.setItem("docmind.chat.activeSessionId", "thread-2")
    getSessionsMock.mockResolvedValue({
      items: [
        { id: "thread-1", title: "第一个问题", created_at: "2026-05-11T09:00:00Z", updated_at: "2026-05-11T10:00:00Z" },
        { id: "thread-2", title: "第二个问题", created_at: "2026-05-11T08:00:00Z", updated_at: "2026-05-11T11:00:00Z" },
      ],
    })
    getHistoryMock.mockResolvedValue({
      messages: [
        {
          id: "m2",
          role: "user",
          content: "请总结第二个问题",
          citations: [],
          created_at: "2026-05-11T11:00:00Z",
        },
      ],
    })

    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    await store.initialize()

    expect(store.sessions).toHaveLength(2)
    expect(store.activeSessionId).toBe("thread-2")
    expect(store.messages).toEqual([])
    expect(getHistoryMock).not.toHaveBeenCalled()
  })

  it("can eagerly hydrate the restored active session when requested", async () => {
    window.localStorage.setItem("docmind.chat.activeSessionId", "thread-2")
    getSessionsMock.mockResolvedValue({
      items: [
        { id: "thread-2", title: "第二个问题", created_at: "2026-05-11T08:00:00Z", updated_at: "2026-05-11T11:00:00Z" },
      ],
    })
    getHistoryMock.mockResolvedValue({
      messages: [
        {
          id: "m2",
          role: "user",
          content: "请总结第二个问题",
          citations: [],
          created_at: "2026-05-11T11:00:00Z",
        },
      ],
    })

    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    await store.initialize({ loadActiveHistory: true })

    expect(store.activeSessionId).toBe("thread-2")
    expect(store.messages[0].content).toBe("请总结第二个问题")
  })

  it("deletes a session and clears the persisted active id when needed", async () => {
    deleteSessionMock.mockResolvedValue({ deleted: true })

    const { useChatStore } = await import("../chat")
    const store = useChatStore()

    store.createSession()
    const sessionId = store.activeSessionId as string
    await store.deleteSession(sessionId)

    expect(deleteSessionMock).toHaveBeenCalledWith(sessionId)
    expect(store.sessions).toEqual([])
    expect(store.activeSessionId).toBeNull()
    expect(window.localStorage.getItem("docmind.chat.activeSessionId")).toBeNull()
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

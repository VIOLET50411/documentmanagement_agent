import { defineStore } from "pinia"
import { computed, ref, type Ref } from "vue"
import { chatApi } from "@/api/chat"
import type { ChatCitation } from "@/api/schemas"

export interface ChatSession {
  id: string
  title: string
  createdAt: string
  updatedAt: string
}

export interface ChatMessage {
  id: string
  role: string
  content: string
  citations: ChatCitation[]
  timestamp: string
}

export interface ChatRuntimeEvent {
  id: string
  status: string
  message: string
  timestamp: string
}

export const useChatStore = defineStore("chat", () => {
  const sessions: Ref<ChatSession[]> = ref([])
  const activeSessionId = ref<string | null>(null)
  const messages: Ref<ChatMessage[]> = ref([])
  const runtimeEvents: Ref<ChatRuntimeEvent[]> = ref([])
  const isStreaming = ref(false)
  const streamStatus = ref("")
  const streamStatusMsg = ref("")

  const activeSession = computed(() => sessions.value.find((session) => session.id === activeSessionId.value) ?? null)

  function formatSessionTitle(content: string) {
    const normalized = content.replace(/\s+/g, " ").trim()
    if (!normalized) return "新对话"
    return normalized.length > 28 ? `${normalized.slice(0, 28)}…` : normalized
  }

  function touchActiveSession(content?: string) {
    const session = sessions.value.find((item) => item.id === activeSessionId.value)
    if (!session) return
    const now = new Date().toISOString()
    session.updatedAt = now
    if (content && session.title === "新对话") {
      session.title = formatSessionTitle(content)
    }
    sessions.value = [...sessions.value].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  }

  function createSession(): ChatSession {
    const now = new Date().toISOString()
    const id = Date.now().toString()
    const session: ChatSession = { id, title: "新对话", createdAt: now, updatedAt: now }
    sessions.value.unshift(session)
    activeSessionId.value = id
    messages.value = []
    runtimeEvents.value = []
    return session
  }

  async function setActiveSession(sessionId: string) {
    activeSessionId.value = sessionId
    messages.value = []
    runtimeEvents.value = []
    try {
      const res = await chatApi.getHistory(sessionId)
      messages.value = (res.messages || []).map((msg) => ({
        id: msg.id,
        role: msg.role,
        content: msg.content,
        citations: msg.citations || [],
        timestamp: msg.created_at,
      }))
    } catch {
      messages.value = []
    }
    touchActiveSession()
  }

  function deleteSession(sessionId: string) {
    sessions.value = sessions.value.filter((session) => session.id !== sessionId)
    if (activeSessionId.value === sessionId) {
      activeSessionId.value = sessions.value[0]?.id || null
      messages.value = []
      runtimeEvents.value = []
    }
  }

  function addMessage(message: Omit<ChatMessage, "id" | "timestamp"> & Partial<Pick<ChatMessage, "id" | "timestamp">>) {
    messages.value.push({
      id: message.id || Date.now().toString(),
      role: message.role,
      content: message.content,
      citations: message.citations || [],
      timestamp: message.timestamp || new Date().toISOString(),
    })
    if (message.role === "user") {
      runtimeEvents.value = []
      touchActiveSession(message.content)
    } else {
      touchActiveSession()
    }
  }

  function updateLastAssistantMessage(content: string) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === "assistant") last.content += content
  }

  function replaceLastAssistantMessage(content: string, citations: ChatCitation[] = []) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === "assistant") {
      last.content = content
      last.citations = citations
    }
  }

  function setLastAssistantMeta({ id, citations }: { id?: string; citations?: ChatCitation[] }) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === "assistant") {
      if (id) last.id = id
      if (Array.isArray(citations)) last.citations = citations
    }
  }

  function setStreamState(status: string, message = "") {
    streamStatus.value = status
    streamStatusMsg.value = message
    isStreaming.value = !["done", "error", ""].includes(status)
    if (["thinking", "searching", "reading", "tool_call", "error"].includes(status)) {
      appendRuntimeEvent(status, message || defaultRuntimeMessage(status))
    }
  }

  function appendRuntimeEvent(status: string, message: string) {
    const normalized = message.trim()
    const last = runtimeEvents.value[runtimeEvents.value.length - 1]
    if (last && last.status === status && last.message === normalized) {
      return
    }
    runtimeEvents.value.push({
      id: `${status}-${Date.now()}-${runtimeEvents.value.length}`,
      status,
      message: normalized,
      timestamp: new Date().toISOString(),
    })
  }

  function clearRuntimeEvents() {
    runtimeEvents.value = []
  }

  function defaultRuntimeMessage(status: string) {
    const labels: Record<string, string> = {
      thinking: "正在理解问题",
      searching: "正在检索知识库",
      reading: "正在读取证据内容",
      tool_call: "正在执行工具调用",
      error: "本轮回答失败",
    }
    return labels[status] || "正在处理"
  }

  function ensureSessionById(sessionId: string | null | undefined) {
    if (!sessionId) return
    const exists = sessions.value.some((session) => session.id === sessionId)
    if (!exists) {
      const now = new Date().toISOString()
      sessions.value.unshift({ id: sessionId, title: "新对话", createdAt: now, updatedAt: now })
    }
    activeSessionId.value = sessionId
    touchActiveSession()
  }

  return {
    sessions,
    activeSessionId,
    messages,
    runtimeEvents,
    isStreaming,
    streamStatus,
    streamStatusMsg,
    activeSession,
    createSession,
    setActiveSession,
    deleteSession,
    addMessage,
    updateLastAssistantMessage,
    replaceLastAssistantMessage,
    setLastAssistantMeta,
    setStreamState,
    clearRuntimeEvents,
    ensureSessionById,
  }
})

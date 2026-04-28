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

export const useChatStore = defineStore("chat", () => {
  const sessions: Ref<ChatSession[]> = ref([])
  const activeSessionId = ref<string | null>(null)
  const messages: Ref<ChatMessage[]> = ref([])
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
    return session
  }

  async function setActiveSession(sessionId: string) {
    activeSessionId.value = sessionId
    messages.value = []
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
    ensureSessionById,
  }
})

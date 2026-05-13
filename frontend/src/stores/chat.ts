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
  eventId?: string
  sequenceNum?: number
  traceId?: string
  source?: string
  degraded?: boolean
  fallbackReason?: string | null
}

const ACTIVE_SESSION_STORAGE_KEY = "docmind.chat.activeSessionId"
const DEFAULT_SESSION_TITLE = "新对话"

export const useChatStore = defineStore("chat", () => {
  const sessions: Ref<ChatSession[]> = ref([])
  const activeSessionId = ref<string | null>(null)
  const messages: Ref<ChatMessage[]> = ref([])
  const runtimeEvents: Ref<ChatRuntimeEvent[]> = ref([])
  const isStreaming = ref(false)
  const streamStatus = ref("")
  const streamStatusMsg = ref("")
  const initialized = ref(false)
  const historyLoadedSessionId = ref<string | null>(null)

  const activeSession = computed(() => sessions.value.find((session) => session.id === activeSessionId.value) ?? null)

  function canUseStorage() {
    return typeof window !== "undefined" && typeof window.localStorage !== "undefined"
  }

  function saveActiveSessionId(sessionId: string | null) {
    if (!canUseStorage()) return
    if (sessionId) {
      window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId)
    } else {
      window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY)
    }
  }

  function loadStoredActiveSessionId() {
    if (!canUseStorage()) return null
    return window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)
  }

  function formatSessionTitle(content: string) {
    const normalized = content.replace(/\s+/g, " ").trim()
    if (!normalized) return DEFAULT_SESSION_TITLE
    const firstChunk = normalized.split(/[。！？\n]/).map((item) => item.trim()).find(Boolean) || normalized
    const compact = firstChunk.replace(/^[#>*\-\d.\s]+/, "").trim()
    const title = compact || normalized
    return title.length > 24 ? `${title.slice(0, 24)}…` : title
  }

  function touchActiveSession(content?: string) {
    const session = sessions.value.find((item) => item.id === activeSessionId.value)
    if (!session) return
    const now = new Date().toISOString()
    session.updatedAt = now
    if (content && session.title === DEFAULT_SESSION_TITLE) {
      session.title = formatSessionTitle(content)
    }
    sessions.value = [...sessions.value].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  }

  function createSessionId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID()
    }
    return `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
  }

  function createSession(): ChatSession {
    const now = new Date().toISOString()
    const id = createSessionId()
    const session: ChatSession = { id, title: DEFAULT_SESSION_TITLE, createdAt: now, updatedAt: now }
    sessions.value = [session, ...sessions.value.filter((item) => item.id !== id)]
    activeSessionId.value = id
    saveActiveSessionId(id)
    messages.value = []
    runtimeEvents.value = []
    return session
  }

  async function setActiveSession(sessionId: string) {
    activeSessionId.value = sessionId
    saveActiveSessionId(sessionId)
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
    historyLoadedSessionId.value = sessionId
    touchActiveSession()
  }

  async function deleteSession(sessionId: string) {
    try {
      await chatApi.deleteSession(sessionId)
    } catch {
      // Keep local state consistent even if backend deletion fails.
    }
    sessions.value = sessions.value.filter((session) => session.id !== sessionId)
    if (activeSessionId.value === sessionId) {
      const nextSessionId = sessions.value[0]?.id || null
      if (nextSessionId) {
        await setActiveSession(nextSessionId)
      } else {
        activeSessionId.value = null
        saveActiveSessionId(null)
        messages.value = []
        runtimeEvents.value = []
      }
    }
  }

  function addMessage(message: Omit<ChatMessage, "id" | "timestamp"> & Partial<Pick<ChatMessage, "id" | "timestamp">>) {
    messages.value.push({
      id: message.id || createSessionId(),
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

  function setStreamState(
    status: string,
    message = "",
    meta: Partial<Pick<ChatRuntimeEvent, "eventId" | "sequenceNum" | "traceId" | "source" | "degraded" | "fallbackReason">> = {}
  ) {
    streamStatus.value = status
    streamStatusMsg.value = message
    isStreaming.value = !["done", "error", ""].includes(status)
    if (["thinking", "searching", "reading", "tool_call", "error"].includes(status)) {
      appendRuntimeEvent(status, message || defaultRuntimeMessage(status), meta)
    }
  }

  function appendRuntimeEvent(
    status: string,
    message: string,
    meta: Partial<Pick<ChatRuntimeEvent, "eventId" | "sequenceNum" | "traceId" | "source" | "degraded" | "fallbackReason">> = {}
  ) {
    const normalized = message.trim()
    const last = runtimeEvents.value[runtimeEvents.value.length - 1]
    if (
      last &&
      last.status === status &&
      last.message === normalized &&
      last.traceId === meta.traceId &&
      last.sequenceNum === meta.sequenceNum
    ) {
      return
    }
    runtimeEvents.value.push({
      id: meta.eventId || `${status}-${Date.now()}-${runtimeEvents.value.length}`,
      status,
      message: normalized,
      timestamp: new Date().toISOString(),
      eventId: meta.eventId,
      sequenceNum: meta.sequenceNum,
      traceId: meta.traceId,
      source: meta.source,
      degraded: meta.degraded,
      fallbackReason: meta.fallbackReason,
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
      sessions.value.unshift({ id: sessionId, title: DEFAULT_SESSION_TITLE, createdAt: now, updatedAt: now })
    }
    activeSessionId.value = sessionId
    saveActiveSessionId(sessionId)
    touchActiveSession()
  }

  async function loadSessions() {
    const res = await chatApi.getSessions()
    sessions.value = res.items.map((item) => ({
      id: item.id,
      title: item.title || DEFAULT_SESSION_TITLE,
      createdAt: item.created_at,
      updatedAt: item.updated_at,
    }))
  }

  async function initialize(options: { loadActiveHistory?: boolean } = {}) {
    if (initialized.value) return
    try {
      await loadSessions()
      const storedId = loadStoredActiveSessionId()
      const firstAvailableId = sessions.value[0]?.id || null
      const nextSessionId = storedId && sessions.value.some((item) => item.id === storedId) ? storedId : firstAvailableId
      if (nextSessionId) {
        activeSessionId.value = nextSessionId
        saveActiveSessionId(nextSessionId)
        if (options.loadActiveHistory) {
          await setActiveSession(nextSessionId)
        } else {
          touchActiveSession()
        }
      } else {
        activeSessionId.value = null
        saveActiveSessionId(null)
        messages.value = []
        runtimeEvents.value = []
        historyLoadedSessionId.value = null
      }
    } finally {
      initialized.value = true
    }
  }

  async function ensureActiveSessionLoaded() {
    if (!activeSessionId.value) return
    if (historyLoadedSessionId.value === activeSessionId.value) return
    await setActiveSession(activeSessionId.value)
  }

  return {
    sessions,
    activeSessionId,
    messages,
    runtimeEvents,
    isStreaming,
    streamStatus,
    streamStatusMsg,
    initialized,
    activeSession,
    initialize,
    ensureActiveSessionLoaded,
    loadSessions,
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

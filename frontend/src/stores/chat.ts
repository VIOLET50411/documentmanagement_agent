import { defineStore } from "pinia"
import { computed, ref, type Ref } from "vue"
import { chatApi } from "@/api/chat"
import type { ChatCitation } from "@/api/schemas"

export interface ChatSession {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  pinned?: boolean
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

export interface AttachedFile {
  id: string
  name: string
  status: 'uploading' | 'queued' | 'parsing' | 'chunking' | 'indexing' | 'ready' | 'failed' | 'partial_failed'
  progress: number
  docId?: string
}

const ACTIVE_SESSION_STORAGE_KEY = "docmind.chat.activeSessionId"
const PINNED_SESSIONS_STORAGE_KEY = "docmind.chat.pinnedSessions"
const DEFAULT_SESSION_TITLE = "新对话"

export const useChatStore = defineStore("chat", () => {
  const sessions: Ref<ChatSession[]> = ref([])
  const activeSessionId = ref<string | null>(null)
  const messages: Ref<ChatMessage[]> = ref([])
  const runtimeEvents: Ref<ChatRuntimeEvent[]> = ref([])
  const attachedFiles: Ref<AttachedFile[]> = ref([])
  const isStreaming = ref(false)
  const streamStatus = ref("")
  const streamStatusMsg = ref("")
  const initialized = ref(false)
  const historyLoadedSessionId = ref<string | null>(null)

  const activeSession = computed(() => sessions.value.find((session) => session.id === activeSessionId.value) ?? null)
  const isHistoryLoading = computed(() => activeSessionId.value !== historyLoadedSessionId.value)

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
    sessions.value = sortSessions([...sessions.value])
  }

  function sortSessions(list: ChatSession[]): ChatSession[] {
    return list.sort((a, b) => {
      if (a.pinned && !b.pinned) return -1
      if (!a.pinned && b.pinned) return 1
      return b.updatedAt.localeCompare(a.updatedAt)
    })
  }

  function loadPinnedSet(): Set<string> {
    if (!canUseStorage()) return new Set()
    try {
      const raw = window.localStorage.getItem(PINNED_SESSIONS_STORAGE_KEY)
      return new Set(raw ? JSON.parse(raw) : [])
    } catch { return new Set() }
  }

  function savePinnedSet(set: Set<string>) {
    if (!canUseStorage()) return
    window.localStorage.setItem(PINNED_SESSIONS_STORAGE_KEY, JSON.stringify([...set]))
  }

  function applyPinnedFlags() {
    const pinned = loadPinnedSet()
    for (const s of sessions.value) {
      s.pinned = pinned.has(s.id)
    }
    sessions.value = sortSessions([...sessions.value])
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
    attachedFiles.value = []
    historyLoadedSessionId.value = id
    return session
  }

  async function setActiveSession(sessionId: string) {
    // Don't reset if we're currently streaming in this session
    if (isStreaming.value && activeSessionId.value === sessionId) return

    activeSessionId.value = sessionId
    saveActiveSessionId(sessionId)
    messages.value = []
    runtimeEvents.value = []
    attachedFiles.value = []
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
    // Optimistic: remove from local state immediately for instant UI feedback
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
    // Fire backend deletion in background (don't block UI)
    chatApi.deleteSession(sessionId).catch(() => {})
  }

  async function clearAllSessions() {
    sessions.value = []
    activeSessionId.value = null
    saveActiveSessionId(null)
    messages.value = []
    runtimeEvents.value = []
    chatApi.deleteAllSessions().catch(() => {})
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
      // Start a new session on launch
      const firstSession = sessions.value[0]
      if (firstSession && firstSession.title === DEFAULT_SESSION_TITLE) {
        // Reuse the existing empty session at the top
        activeSessionId.value = firstSession.id
        saveActiveSessionId(firstSession.id)
        if (options.loadActiveHistory) {
          await setActiveSession(firstSession.id)
        }
      } else {
        // Create a new session and activate it
        createSession()
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

  async function reloadActiveSession() {
    if (!activeSessionId.value) return
    if (isStreaming.value) return
    try {
      const res = await chatApi.getHistory(activeSessionId.value)
      const freshMessages = (res.messages || []).map((msg) => ({
        id: msg.id,
        role: msg.role,
        content: msg.content,
        citations: msg.citations || [],
        timestamp: msg.created_at,
      }))
      // Only replace if backend has non-empty assistant content
      // that our in-memory state is missing
      const lastInMemory = messages.value[messages.value.length - 1]
      const lastFromDb = freshMessages[freshMessages.length - 1]
      if (
        lastFromDb &&
        lastFromDb.role === "assistant" &&
        lastFromDb.content &&
        (!lastInMemory || !lastInMemory.content || lastInMemory.content.length < lastFromDb.content.length)
      ) {
        messages.value = freshMessages
      } else if (freshMessages.length > 0 && messages.value.length === 0) {
        messages.value = freshMessages
      }
      historyLoadedSessionId.value = activeSessionId.value
    } catch {
      // Silently fail — don't disrupt the user experience
    }
  }

  function clearAttachedFiles() {
    attachedFiles.value = []
  }

  function resetToNew() {
    activeSessionId.value = null
    saveActiveSessionId(null)
    messages.value = []
    runtimeEvents.value = []
    attachedFiles.value = []
    historyLoadedSessionId.value = null
  }

  function removeLastMessage() {
    if (messages.value.length > 0) {
      messages.value.pop()
    }
  }

  function renameSession(sessionId: string, newTitle: string) {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      session.title = newTitle.trim() || DEFAULT_SESSION_TITLE
    }
  }

  function togglePin(sessionId: string) {
    const pinned = loadPinnedSet()
    if (pinned.has(sessionId)) {
      pinned.delete(sessionId)
    } else {
      pinned.add(sessionId)
    }
    savePinnedSet(pinned)
    applyPinnedFlags()
  }

  function exportAsMarkdown(): string {
    const session = sessions.value.find((s) => s.id === activeSessionId.value)
    const title = session?.title || '未命名对话'
    const date = new Date().toLocaleDateString('zh-CN')
    let md = `# ${title}\n\n> 导出时间: ${date}\n\n---\n\n`
    for (const msg of messages.value) {
      if (msg.role === 'user') {
        md += `### 🧑 用户\n\n${msg.content}\n\n`
      } else {
        md += `### 🤖 DocMind\n\n${msg.content}\n\n`
        if (msg.citations?.length) {
          md += `**引用来源:**\n`
          for (const c of msg.citations) {
            md += `- ${c.doc_title || '未知文档'} (${c.section_title || ''}, 页码 ${c.page_number || '-'})\n`
          }
          md += `\n`
        }
      }
      md += `---\n\n`
    }
    return md
  }

  return {
    sessions,
    activeSessionId,
    messages,
    runtimeEvents,
    attachedFiles,
    isStreaming,
    streamStatus,
    streamStatusMsg,
    initialized,
    activeSession,
    isHistoryLoading,
    initialize,
    ensureActiveSessionLoaded,
    reloadActiveSession,
    loadSessions,
    createSession,
    setActiveSession,
    deleteSession,
    clearAllSessions,
    addMessage,
    updateLastAssistantMessage,
    replaceLastAssistantMessage,
    setLastAssistantMeta,
    setStreamState,
    clearRuntimeEvents,
    ensureSessionById,
    clearAttachedFiles,
    resetToNew,
    removeLastMessage,
    renameSession,
    togglePin,
    exportAsMarkdown,
    applyPinnedFlags,
  }
})

import { ref, type Ref } from "vue"
import { useChatStore } from "@/stores/chat"
import { chatApi } from "@/api/chat"

interface RuntimeEvent {
  status: string
  msg?: string
  token?: string
  content?: string
  answer?: string
  citations?: any[]
  message_id?: string
  thread_id?: string
  event_id?: string
  sequence_num?: number
  trace_id?: string
  source?: string
  degraded?: boolean
  fallback_reason?: string | null
}

const transientStreamingContent = new Set([
  "正在生成回答...",
  "正在生成回答…",
])

export function useSSE() {
  const error: Ref<string | null> = ref(null)
  const chatStore = useChatStore()

  async function sendMessage(message: string, threadId: string | null = null, modelName: string | null = null) {
    error.value = null
    const targetThreadId = threadId || chatStore.createSession().id
    chatStore.setStreamState("thinking", "正在理解您的问题...")
    chatStore.addMessage({ role: "user", content: message, citations: [] })
    chatStore.addMessage({ role: "assistant", content: "", citations: [] })

    try {
      const response = await chatApi.streamChat(message, targetThreadId, modelName)

      // Handle 401 - token expired, force logout
      if (response.status === 401) {
        const { useAuthStore } = await import("@/stores/auth")
        const authStore = useAuthStore()
        authStore.logout()
        return
      }

      if (!response.ok || !response.body) throw new Error(`SSE request failed: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let receivedDone = false
      let hasReceivedContent = false

      let fullAnswer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split("\n\n")
        buffer = chunks.pop() || ""

        for (const chunk of chunks) {
          const idLine = chunk
            .split("\n")
            .find((line) => line.startsWith("id: "))
          const dataLines = chunk
            .split("\n")
            .filter((line) => line.startsWith("data: "))
            .map((line) => line.slice(6))
          if (dataLines.length === 0) continue
          try {
            const parsed = JSON.parse(dataLines.join("\n")) as RuntimeEvent
            if (idLine && !parsed.event_id) {
              parsed.event_id = idLine.slice(4).trim()
            }
            if (parsed.status === "done") receivedDone = true
            if (parsed.status === "streaming") {
              hasReceivedContent = true
              if (parsed.content && !transientStreamingContent.has(parsed.content.trim())) {
                fullAnswer = parsed.content
              } else if (parsed.token) {
                fullAnswer += parsed.token
              }
            }
            handleEvent(parsed, targetThreadId, fullAnswer)
          } catch {
            // Ignore malformed events from interrupted streams.
          }
        }
      }

      // Stream ended without a "done" event — connection dropped.
      if (!receivedDone) {
        if (targetThreadId === chatStore.activeSessionId) {
          const lastMsg = chatStore.messages[chatStore.messages.length - 1]
          if (lastMsg && lastMsg.role === "assistant" && !lastMsg.content && !fullAnswer) {
            chatStore.removeLastMessage()
          }
          if (hasReceivedContent) {
            chatStore.replaceLastAssistantMessage(fullAnswer)
            chatStore.setStreamState("done")
          } else {
            chatStore.setStreamState("error", "连接中断")
          }
        }
      }
    } catch (caught) {
      const messageText = caught instanceof Error ? caught.message : "连接失败"
      error.value = messageText
      if (targetThreadId === chatStore.activeSessionId) {
        const lastMsg = chatStore.messages[chatStore.messages.length - 1]
        if (lastMsg && lastMsg.role === "assistant" && !lastMsg.content) {
          chatStore.removeLastMessage()
        }
        chatStore.setStreamState("error", messageText)
      }
    }
  }

  function handleEvent(event: RuntimeEvent, targetThreadId: string, fullAnswer: string) {
    // Only update UI if the user is still looking at this session
    const isActive = targetThreadId === chatStore.activeSessionId

    const meta = {
      eventId: event.event_id,
      sequenceNum: event.sequence_num,
      traceId: event.trace_id,
      source: event.source,
      degraded: event.degraded,
      fallbackReason: event.fallback_reason,
    }

    switch (event.status) {
      case "thinking":
      case "searching":
      case "reading":
      case "tool_call":
        if (isActive) {
          chatStore.setStreamState(event.status, event.msg || "", meta)
        }
        break
      case "streaming":
        if (isActive) {
          chatStore.setStreamState("streaming")
          chatStore.replaceLastAssistantMessage(fullAnswer, event.citations || [])
        }
        break
      case "error":
        if (isActive) {
          chatStore.replaceLastAssistantMessage(fullAnswer || event.msg || "请求失败")
          chatStore.setStreamState("error", event.msg || "请求失败", meta)
        }
        break
      case "done":
        if (isActive) {
          if (event.answer || fullAnswer) {
            chatStore.replaceLastAssistantMessage(event.answer || fullAnswer, event.citations || [])
          }
          chatStore.setLastAssistantMeta({ id: event.message_id, citations: event.citations || [] })
          chatStore.setStreamState("done")
        }
        chatStore.ensureSessionById(targetThreadId)
        void chatStore.loadSessions().catch(() => {})
        break
    }
  }

  return { sendMessage, error }
}

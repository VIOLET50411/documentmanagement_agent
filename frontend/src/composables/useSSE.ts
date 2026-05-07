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
    chatStore.setStreamState("thinking", "正在理解您的问题...")
    chatStore.addMessage({ role: "user", content: message, citations: [] })
    chatStore.addMessage({ role: "assistant", content: "", citations: [] })

    try {
      const response = await chatApi.streamChat(message, threadId, modelName)
      if (!response.ok || !response.body) throw new Error(`SSE request failed: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

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
            handleEvent(parsed)
          } catch {
            // Ignore malformed events from interrupted streams.
          }
        }
      }
    } catch (caught) {
      const messageText = caught instanceof Error ? caught.message : "连接失败"
      error.value = messageText
      chatStore.replaceLastAssistantMessage("请求失败，请稍后重试。")
      chatStore.setStreamState("error", messageText)
    }
  }

  function handleEvent(event: RuntimeEvent) {
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
        chatStore.setStreamState(event.status, event.msg || "", meta)
        break
      case "streaming":
        chatStore.setStreamState("streaming")
        if (event.content && !transientStreamingContent.has(event.content.trim())) {
          chatStore.replaceLastAssistantMessage(event.content, event.citations || [])
        } else if (event.token) {
          chatStore.updateLastAssistantMessage(event.token)
        }
        break
      case "error":
        chatStore.replaceLastAssistantMessage(event.msg || "请求失败")
        chatStore.setStreamState("error", event.msg || "请求失败", meta)
        break
      case "done":
        if (event.answer) {
          chatStore.replaceLastAssistantMessage(event.answer, event.citations || [])
        }
        chatStore.setLastAssistantMeta({ id: event.message_id, citations: event.citations || [] })
        chatStore.ensureSessionById(event.thread_id)
        chatStore.setStreamState("done")
        break
    }
  }

  return { sendMessage, error }
}

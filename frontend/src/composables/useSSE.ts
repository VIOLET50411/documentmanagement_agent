import { ref, type Ref } from "vue"
import { useChatStore } from "@/stores/chat"
import { chatApi } from "@/api/chat"

interface RuntimeEvent {
  status: string
  msg?: string
  token?: string
  content?: string
  citations?: any[]
  message_id?: string
  thread_id?: string
}

export function useSSE() {
  const error: Ref<string | null> = ref(null)
  const chatStore = useChatStore()

  async function sendMessage(message: string, threadId: string | null = null) {
    error.value = null
    chatStore.setStreamState("thinking", "正在理解您的问题...")
    chatStore.addMessage({ role: "user", content: message, citations: [] })
    chatStore.addMessage({ role: "assistant", content: "", citations: [] })

    try {
      const response = await chatApi.streamChat(message, threadId)
      if (!response.ok || !response.body) throw new Error(`SSE request failed: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          try {
            handleEvent(JSON.parse(line.slice(6)) as RuntimeEvent)
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
    switch (event.status) {
      case "thinking":
      case "searching":
      case "reading":
      case "tool_call":
        chatStore.setStreamState(event.status, event.msg || "")
        break
      case "streaming":
        chatStore.setStreamState("streaming")
        if (event.content) {
          chatStore.replaceLastAssistantMessage(event.content, event.citations || [])
        } else if (event.token) {
          chatStore.updateLastAssistantMessage(event.token)
        }
        break
      case "error":
        chatStore.replaceLastAssistantMessage(event.msg || "请求失败")
        chatStore.setStreamState("error", event.msg || "请求失败")
        break
      case "done":
        chatStore.setLastAssistantMeta({ id: event.message_id, citations: event.citations || [] })
        chatStore.ensureSessionById(event.thread_id)
        chatStore.setStreamState("done")
        break
    }
  }

  return { sendMessage, error }
}

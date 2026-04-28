import { onUnmounted, ref, type Ref } from "vue"
import { useChatStore } from "@/stores/chat"

type WsMessage = {
  type?: string
  msg?: string
  status?: string
  content?: string
  answer?: string
  citations?: any[]
  message_id?: string
  [key: string]: any
}

const WS_BASE_URL = import.meta.env.VITE_WS_URL || `ws://${window.location.host}/api/v1/ws/chat`

export function useWebSocketChat() {
  const chatStore = useChatStore()
  const isConnected = ref(false)
  const reconnectAttempts = ref(0)
  const maxReconnectAttempts = 5

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null

  async function connect(token: string) {
    return new Promise<void>((resolve, reject) => {
      try {
        ws = new WebSocket(WS_BASE_URL)

        ws.onopen = () => {
          ws?.send(JSON.stringify({ type: "auth", token }))
        }

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data) as WsMessage
            handleMessage(data, resolve)
          } catch {
            console.error("Failed to parse WebSocket message:", event.data)
          }
        }

        ws.onclose = (event) => {
          isConnected.value = false
          stopHeartbeat()

          if (event.code !== 1000 && reconnectAttempts.value < maxReconnectAttempts) {
            scheduleReconnect(token)
          }
        }

        ws.onerror = (error) => {
          console.error("WebSocket error:", error)
          reject(error)
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  function handleMessage(data: WsMessage, authResolve?: () => void) {
    switch (data.type) {
      case "auth_ok":
        isConnected.value = true
        reconnectAttempts.value = 0
        startHeartbeat()
        authResolve?.()
        break

      case "error":
        if (!isConnected.value) authResolve?.()
        console.error("Server error:", data.msg)
        break

      case "status":
        chatStore.setStreamState(data.status || "thinking", data.msg || "")
        break

      case "token": {
        if (data.content) {
          const messages = chatStore.messages
          if (messages.length > 0) {
            const lastMessage = messages[messages.length - 1]
            if (lastMessage.role === "assistant") {
              lastMessage.content += data.content
            }
          }
          chatStore.setStreamState("streaming")
        }
        break
      }

      case "done": {
        chatStore.setStreamState("done")
        const messages = chatStore.messages
        if (messages.length > 0) {
          const lastMessage = messages[messages.length - 1]
          if (lastMessage.role === "assistant") {
            if (data.answer && !lastMessage.content) {
              lastMessage.content = data.answer
            }
            lastMessage.citations = data.citations || []
            lastMessage.id = data.message_id || lastMessage.id
          }
        }
        break
      }

      case "pong":
        break

      default:
        console.warn("Unknown WebSocket message type:", data)
    }
  }

  function sendMessage(content: string, threadId: string | null = null, searchType = "hybrid") {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.error("WebSocket is not connected")
      return
    }

    chatStore.addMessage({
      id: `user-${Date.now()}`,
      role: "user",
      content,
      citations: [],
    })

    chatStore.addMessage({
      id: `assistant-${Date.now()}`,
      role: "assistant",
      content: "",
      citations: [],
    })

    chatStore.setStreamState("thinking", "正在理解您的问题...")

    ws.send(
      JSON.stringify({
        type: "message",
        content,
        thread_id: threadId || chatStore.activeSessionId,
        search_type: searchType,
      })
    )
  }

  function disconnect() {
    stopHeartbeat()
    clearReconnectTimer()
    if (ws) {
      ws.close(1000, "Client disconnect")
      ws = null
    }
    isConnected.value = false
  }

  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }))
      }
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  function scheduleReconnect(token: string) {
    clearReconnectTimer()
    const delay = Math.min(1000 * 2 ** reconnectAttempts.value, 30000)
    reconnectAttempts.value += 1
    reconnectTimer = setTimeout(() => {
      connect(token).catch(() => undefined)
    }, delay)
  }

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect,
    sendMessage,
    disconnect,
    isConnected: isConnected as Ref<boolean>,
    reconnectAttempts,
  }
}

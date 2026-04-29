import { apiGet, apiPost } from "./http"
import { chatHistorySchema, type ChatHistoryResponse } from "./schemas"
import { getAbsoluteApiBaseUrl } from "@/mobile/capacitor"
import { useAuthStore } from "@/stores/auth"

export const chatApi = {
  streamChat(message: string, threadId: string | null = null) {
    const authStore = useAuthStore()
    const body = JSON.stringify({ message, thread_id: threadId })
    const base = getAbsoluteApiBaseUrl()

    return fetch(`${base}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${authStore.token}`,
      },
      body,
    })
  },

  async getHistory(threadId: string): Promise<ChatHistoryResponse> {
    return chatHistorySchema.parse(await apiGet<ChatHistoryResponse>("/chat/history", { params: { thread_id: threadId } }))
  },

  submitFeedback(messageId: string, rating: number, correction: string | null = null) {
    return apiPost("/chat/feedback", null, {
      params: { message_id: messageId, rating, correction },
    })
  },
}

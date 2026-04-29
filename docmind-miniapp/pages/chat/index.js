const { apiRequest } = require('../../utils/api')
const { getStorage, setStorage } = require('../../utils/auth')

const THREAD_KEY = 'chat_thread_id'

Page({
  data: {
    messages: [],
    input: '',
    loading: false,
    statusText: '\u51c6\u5907\u5c31\u7eea',
    threadId: '',
  },

  onShow() {
    const token = getStorage('access_token')
    if (!token) {
      wx.redirectTo({ url: '/pages/login/index' })
      return
    }
    const threadId = getStorage(THREAD_KEY)
    this.setData({ threadId })
    if (threadId) {
      this.loadHistory(threadId)
    }
  },

  onInput(event) {
    this.setData({ input: event.detail.value })
  },

  async loadHistory(threadId) {
    this.setData({ statusText: '\u6b63\u5728\u52a0\u8f7d\u5386\u53f2\u8bb0\u5f55...' })
    try {
      const response = await apiRequest({ url: `/chat/history?thread_id=${encodeURIComponent(threadId)}` })
      const data = response.data || {}
      this.setData({ messages: data.messages || [], statusText: '\u5386\u53f2\u8bb0\u5f55\u5df2\u52a0\u8f7d' })
    } catch (error) {
      console.error('loadHistory failed', error)
      this.setData({ statusText: '\u52a0\u8f7d\u5386\u53f2\u8bb0\u5f55\u5931\u8d25' })
    }
  },

  async sendMessage() {
    if (this.data.loading || !this.data.input.trim()) return
    const content = this.data.input.trim()
    const nextMessages = this.data.messages.concat([{ role: 'user', content }])
    this.setData({
      loading: true,
      input: '',
      statusText: '\u6b63\u5728\u751f\u6210\u56de\u7b54...',
      messages: nextMessages,
    })

    try {
      const response = await apiRequest({
        url: '/chat/message',
        method: 'POST',
        data: {
          message: content,
          thread_id: this.data.threadId || undefined,
          search_type: 'hybrid',
        },
      })
      const data = response.data || {}
      if (data.thread_id) {
        setStorage(THREAD_KEY, data.thread_id)
      }
      this.setData({
        threadId: data.thread_id || this.data.threadId,
        messages: nextMessages.concat([{ role: 'assistant', content: data.answer || '\u672a\u8fd4\u56de\u5185\u5bb9' }]),
        statusText: '\u56de\u7b54\u5b8c\u6210',
      })
    } catch (error) {
      console.error('sendMessage failed', error)
      this.setData({
        messages: nextMessages,
        statusText: '\u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5',
      })
    } finally {
      this.setData({ loading: false })
    }
  },
})

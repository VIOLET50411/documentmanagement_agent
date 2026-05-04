const { apiRequest } = require('../../utils/api')
const { getStorage, setStorage } = require('../../utils/auth')
const { connectChatSocket } = require('../../utils/ws')

const THREAD_KEY = 'chat_thread_id'

Page({
  data: {
    messages: [],
    input: '',
    loading: false,
    statusText: '准备就绪',
    threadId: '',
  },

  socketTask: null,
  pendingMessage: '',
  assistantReplyBuffer: '',

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

  onHide() {
    this.closeSocket()
  },

  onUnload() {
    this.closeSocket()
  },

  onInput(event) {
    this.setData({ input: event.detail.value })
  },

  async loadHistory(threadId) {
    this.setData({ statusText: '正在加载历史记录...' })
    try {
      const response = await apiRequest({ url: `/chat/history?thread_id=${encodeURIComponent(threadId)}` })
      const data = response.data || {}
      this.setData({ messages: data.messages || [], statusText: '历史记录已加载' })
    } catch (error) {
      console.error('loadHistory failed', error)
      this.setData({ statusText: '加载历史记录失败' })
    }
  },

  async sendMessage() {
    if (this.data.loading || !this.data.input.trim()) return
    const token = getStorage('access_token')
    if (!token) {
      wx.redirectTo({ url: '/pages/login/index' })
      return
    }

    const content = this.data.input.trim()
    const nextMessages = this.data.messages.concat([{ role: 'user', content }])
    this.pendingMessage = content
    this.assistantReplyBuffer = ''
    this.setData({
      loading: true,
      input: '',
      statusText: '正在生成回答...',
      messages: nextMessages,
    })

    this.closeSocket()
    this.socketTask = connectChatSocket({
      token,
      onOpen: () => {
        this.socketTask.send({
          data: JSON.stringify({
            type: 'message',
            content,
            thread_id: this.data.threadId || undefined,
            search_type: 'hybrid',
          }),
        })
      },
      onMessage: (payload) => this.handleSocketPayload(payload),
      onClose: () => {
        if (this.data.loading) {
          this.setData({ loading: false })
        }
      },
    })
  },

  handleSocketPayload(payload) {
    const type = payload && payload.type
    if (type === 'auth_ok') {
      this.setData({ statusText: '连接已认证，正在发送消息...' })
      return
    }

    if (type === 'status') {
      this.setData({ statusText: payload.msg || payload.status || '处理中...' })
      return
    }

    if (type === 'token') {
      this.assistantReplyBuffer += payload.content || ''
      this.patchAssistantMessage(this.assistantReplyBuffer)
      return
    }

    if (type === 'done') {
      const threadId = payload.thread_id || this.data.threadId
      if (threadId) {
        setStorage(THREAD_KEY, threadId)
      }
      const answer = payload.answer || this.assistantReplyBuffer || '未返回内容'
      this.patchAssistantMessage(answer)
      this.setData({
        threadId,
        loading: false,
        statusText: '回答完成',
      })
      this.closeSocket()
      return
    }

    if (type === 'error') {
      console.error('chat socket error payload', payload)
      this.setData({
        loading: false,
        statusText: payload.msg || '请求失败，请稍后重试',
      })
      this.closeSocket()
    }
  },

  patchAssistantMessage(content) {
    const messages = this.data.messages.slice()
    const last = messages[messages.length - 1]
    if (last && last.role === 'assistant') {
      last.content = content
    } else {
      messages.push({ role: 'assistant', content })
    }
    this.setData({ messages })
  },

  closeSocket() {
    if (this.socketTask) {
      try {
        this.socketTask.close()
      } catch (error) {
        console.error('closeSocket failed', error)
      }
      this.socketTask = null
    }
  },
})

const { apiRequest } = require('../../utils/api')
const { getStorage, setStorage } = require('../../utils/auth')

Page({
  data: {
    documents: [],
    query: '',
    loading: false,
    searchLoading: false,
    searchResults: [],
    error: '',
  },

  onShow() {
    if (!getStorage('access_token')) {
      wx.redirectTo({ url: '/pages/login/index' })
      return
    }
    this.loadDocuments()
  },

  onPullDownRefresh() {
    this.loadDocuments().finally(() => wx.stopPullDownRefresh())
  },

  onQueryInput(event) {
    this.setData({ query: event.detail.value })
  },

  async loadDocuments() {
    this.setData({ loading: true, error: '' })
    try {
      const response = await apiRequest({ url: '/documents/?page=1&size=20' })
      const data = response.data || {}
      console.log('loadDocuments ok', data)
      this.setData({ documents: data.documents || [] })
    } catch (error) {
      console.error('loadDocuments failed', error)
      this.setData({ error: '\u52a0\u8f7d\u6587\u6863\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002' })
    } finally {
      this.setData({ loading: false })
    }
  },

  async searchDocuments() {
    if (!this.data.query.trim()) {
      this.setData({ searchResults: [] })
      return
    }
    this.setData({ searchLoading: true, error: '' })
    try {
      const response = await apiRequest({
        url: `/search/?q=${encodeURIComponent(this.data.query.trim())}&top_k=10&search_type=hybrid`,
      })
      const data = response.data || {}
      console.log('searchDocuments ok', data)
      this.setData({ searchResults: data.results || [] })
    } catch (error) {
      console.error('searchDocuments failed', error)
      this.setData({ error: '\u68c0\u7d22\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002' })
    } finally {
      this.setData({ searchLoading: false })
    }
  },

  goChat() {
    wx.switchTab({ url: '/pages/chat/index' })
  },

  logout() {
    setStorage('access_token', '')
    setStorage('refresh_token', '')
    wx.redirectTo({ url: '/pages/login/index' })
  },
})

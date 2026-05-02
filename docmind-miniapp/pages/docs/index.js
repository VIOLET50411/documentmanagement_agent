const { apiRequest } = require('../../utils/api')
const { getStorage, setStorage } = require('../../utils/auth')
const { getCachedBootstrap } = require('../../utils/config')
const { buildMiniappDebugDeviceProfile } = require('../../utils/device')

Page({
  data: {
    documents: [],
    query: '',
    loading: false,
    searchLoading: false,
    searchResults: [],
    pushSummary: null,
    pushEvents: [],
    bootstrapStatus: '',
    deviceRegistering: false,
    deviceHeartbeatLoading: false,
    notificationSending: false,
    error: '',
  },

  onShow() {
    if (!getStorage('access_token')) {
      wx.redirectTo({ url: '/pages/login/index' })
      return
    }
    const cachedBootstrap = getCachedBootstrap()
    this.setData({
      bootstrapStatus:
        cachedBootstrap &&
        cachedBootstrap.auth &&
        cachedBootstrap.auth.miniapp &&
        cachedBootstrap.auth.miniapp.ready
          ? 'bootstrap 已同步'
          : '尚未同步 bootstrap',
    })
    this.refreshDeviceStatus()
    this.loadDocuments()
  },

  onPullDownRefresh() {
    Promise.allSettled([this.refreshDeviceStatus(), this.loadDocuments()]).finally(() => wx.stopPullDownRefresh())
  },

  onQueryInput(event) {
    this.setData({ query: event.detail.value })
  },

  async loadDocuments() {
    this.setData({ loading: true, error: '' })
    try {
      const response = await apiRequest({ url: '/documents?page=1&size=20' })
      const data = response.data || {}
      this.setData({ documents: data.documents || [] })
    } catch (error) {
      console.error('loadDocuments failed', error)
      this.setData({ error: '加载文档失败，请稍后重试。' })
    } finally {
      this.setData({ loading: false })
    }
  },

  async loadPushSummary() {
    try {
      const deviceProfile = buildMiniappDebugDeviceProfile()
      const response = await apiRequest({
        url: `/notifications/devices/summary?current_token=${encodeURIComponent(deviceProfile.device_token)}`,
      })
      this.setData({ pushSummary: response.data || null })
    } catch (error) {
      console.error('loadPushSummary failed', error)
    }
  },

  async loadPushEvents() {
    try {
      const response = await apiRequest({ url: '/notifications/events?limit=5' })
      const payload = response.data || {}
      this.setData({ pushEvents: payload.items || [] })
    } catch (error) {
      console.error('loadPushEvents failed', error)
    }
  },

  async refreshDeviceStatus() {
    await Promise.allSettled([this.loadPushSummary(), this.loadPushEvents()])
  },

  async registerCurrentDevice() {
    this.setData({ deviceRegistering: true, error: '' })
    try {
      const deviceProfile = buildMiniappDebugDeviceProfile()
      await apiRequest({
        url: '/notifications/devices',
        method: 'POST',
        data: deviceProfile,
      })
      await this.refreshDeviceStatus()
    } catch (error) {
      console.error('registerCurrentDevice failed', error)
      this.setData({ error: '登记当前终端失败，请稍后重试。' })
    } finally {
      this.setData({ deviceRegistering: false })
    }
  },

  async heartbeatCurrentDevice() {
    this.setData({ deviceHeartbeatLoading: true, error: '' })
    try {
      const deviceProfile = buildMiniappDebugDeviceProfile()
      await apiRequest({
        url: '/notifications/devices/heartbeat',
        method: 'POST',
        data: {
          device_token: deviceProfile.device_token,
          app_version: deviceProfile.app_version,
        },
      })
      await this.refreshDeviceStatus()
    } catch (error) {
      console.error('heartbeatCurrentDevice failed', error)
      this.setData({ error: '刷新终端状态失败，请先完成登记。' })
    } finally {
      this.setData({ deviceHeartbeatLoading: false })
    }
  },

  async sendTestNotification() {
    this.setData({ notificationSending: true, error: '' })
    try {
      await apiRequest({
        url: '/notifications/test',
        method: 'POST',
        data: {
          title: 'DocMind 小程序调试通知',
          body: '这是一次移动端调试通知，用于验证通知链路是否打通。',
        },
      })
      await this.refreshDeviceStatus()
    } catch (error) {
      console.error('sendTestNotification failed', error)
      this.setData({ error: '发送测试通知失败，请确认当前终端已登记。' })
    } finally {
      this.setData({ notificationSending: false })
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
        url: `/search?q=${encodeURIComponent(this.data.query.trim())}&top_k=10&search_type=hybrid`,
      })
      const data = response.data || {}
      this.setData({ searchResults: data.results || [] })
    } catch (error) {
      console.error('searchDocuments failed', error)
      this.setData({ error: '检索失败，请稍后重试。' })
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

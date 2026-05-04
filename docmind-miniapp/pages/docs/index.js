const { apiRequest } = require('../../utils/api')
const { getStorage, setStorage } = require('../../utils/auth')
const { getCachedBootstrap, fetchBootstrapConfig } = require('../../utils/config')
const {
  WECHAT_OPENID_KEY,
  WECHAT_SUBSCRIPTION_STATE_KEY,
  buildMiniappDebugDeviceProfile,
  buildMiniappDeviceProfile,
} = require('../../utils/device')

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
    wechatTemplateId: '',
    wechatSubscribeStatus: '未绑定',
    wechatOpenidBound: false,
    wechatLastBindMessage: '',
    wechatSubscriptionAdvice: '建议在每次关键通知前重新申请一次订阅消息授权。',
    wechatBinding: false,
    businessNotificationPreparing: false,
    deviceRegistering: false,
    deviceHeartbeatLoading: false,
    notificationSending: false,
    error: '',
  },

  async onShow() {
    if (!getStorage('access_token')) {
      wx.redirectTo({ url: '/pages/login/index' })
      return
    }
    await this.ensureBootstrapReady()
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
      const openid = getStorage(WECHAT_OPENID_KEY)
      const deviceProfile = openid ? buildMiniappDeviceProfile(openid) : buildMiniappDebugDeviceProfile()
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

  async ensureBootstrapReady() {
    const app = getApp()
    let cachedBootstrap = getCachedBootstrap()
    let bootstrapStatus = '尚未同步 bootstrap'
    let error = ''

    const hasTemplate =
      cachedBootstrap &&
      cachedBootstrap.auth &&
      cachedBootstrap.auth.miniapp &&
      cachedBootstrap.auth.miniapp.subscribe_template_id

    if (!hasTemplate) {
      try {
        cachedBootstrap = await fetchBootstrapConfig(app.globalData.apiBase)
      } catch (bootstrapError) {
        console.error('ensureBootstrapReady failed', bootstrapError)
        error = '自动同步 bootstrap 失败，请检查后端地址是否可访问。'
      }
    }

    if (
      cachedBootstrap &&
      cachedBootstrap.auth &&
      cachedBootstrap.auth.miniapp &&
      cachedBootstrap.auth.miniapp.ready
    ) {
      bootstrapStatus = 'bootstrap 已同步'
    }

    this.setData({
      bootstrapStatus,
      wechatTemplateId:
        (cachedBootstrap &&
          cachedBootstrap.auth &&
          cachedBootstrap.auth.miniapp &&
          cachedBootstrap.auth.miniapp.subscribe_template_id) ||
        '',
      wechatSubscribeStatus: getStorage(WECHAT_OPENID_KEY) ? '已绑定' : '未绑定',
      wechatOpenidBound: Boolean(getStorage(WECHAT_OPENID_KEY)),
      wechatLastBindMessage: '',
      wechatSubscriptionAdvice: this.buildSubscriptionAdvice(),
      error,
    })
  },

  async bindWechatSubscription() {
    return this.ensureFreshWechatSubscription({ forcePrompt: true, reason: 'manual_bind' })
  },

  async prepareBusinessNotifications({ forcePrompt = true } = {}) {
    this.setData({ businessNotificationPreparing: true, error: '' })
    try {
      const result = await this.ensureFreshWechatSubscription({
        forcePrompt,
        reason: 'document_status_notification',
      })
      if (!result.ok) {
        this.setData({
          error: forcePrompt ? '未完成文档处理通知授权，本次不会接收新的处理结果通知。' : '',
        })
        return result
      }
      this.setData({
        wechatLastBindMessage: forcePrompt
          ? '文档处理结果通知授权已更新，后续异步处理完成时可直接推送。'
          : this.data.wechatLastBindMessage,
      })
      return result
    } finally {
      this.setData({ businessNotificationPreparing: false })
    }
  },

  readSubscriptionState() {
    const raw = getStorage(WECHAT_SUBSCRIPTION_STATE_KEY)
    if (!raw) return null
    if (typeof raw === 'object') return raw
    try {
      return JSON.parse(raw)
    } catch (error) {
      return null
    }
  },

  saveSubscriptionState(state) {
    setStorage(WECHAT_SUBSCRIPTION_STATE_KEY, JSON.stringify(state))
  },

  buildSubscriptionAdvice() {
    const state = this.readSubscriptionState()
    if (!state || !state.granted_at_ms) {
      return '建议先完成一次授权绑定；关键通知发送前会再次请求订阅。'
    }
    return `上次授权：${state.granted_at_label || '未知'}，关键通知发送前会再次请求订阅。`
  },

  shouldPromptSubscriptionAgain() {
    const state = this.readSubscriptionState()
    if (!state || state.last_result !== 'accept') {
      return true
    }
    const grantedAt = Number(state.granted_at_ms || 0)
    if (!grantedAt) {
      return true
    }
    return Date.now() - grantedAt > 12 * 60 * 60 * 1000
  },

  async ensureFreshWechatSubscription({ forcePrompt = false, reason = 'general' } = {}) {
    const templateId = String(this.data.wechatTemplateId || '').trim()
    if (!templateId) {
      this.setData({ error: '当前未拿到订阅模板 ID，请先同步 bootstrap 或检查后端配置。' })
      return { ok: false, reason: 'missing_template_id' }
    }
    if (!forcePrompt && !this.shouldPromptSubscriptionAgain() && getStorage(WECHAT_OPENID_KEY)) {
      return { ok: true, reused: true }
    }
    this.setData({ wechatBinding: true, error: '', wechatLastBindMessage: '' })
    try {
      const subscribeResult = await this.requestWechatSubscription(templateId)
      const now = new Date()
      this.saveSubscriptionState({
        template_id: templateId,
        last_result: subscribeResult,
        last_reason: reason,
        granted_at_ms: subscribeResult === 'accept' ? now.getTime() : 0,
        granted_at_label:
          subscribeResult === 'accept'
            ? `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
            : '',
      })
      if (subscribeResult !== 'accept') {
        this.setData({
          wechatSubscribeStatus: subscribeResult === 'reject' ? '已拒绝' : '未授权',
          wechatLastBindMessage: '你没有同意本次订阅消息授权，后端不会保存微信推送设备。',
          wechatSubscriptionAdvice: this.buildSubscriptionAdvice(),
        })
        return { ok: false, reason: subscribeResult }
      }
      const loginCode = await this.fetchWechatLoginCode()
      const deviceProfile = buildMiniappDebugDeviceProfile()
      const response = await apiRequest({
        url: '/notifications/wechat/subscribe-bind',
        method: 'POST',
        data: {
          js_code: loginCode,
          device_name: deviceProfile.device_name,
          app_version: deviceProfile.app_version,
          subscription_result: subscribeResult,
        },
      })
      const payload = response.data || {}
      if (payload.device_token) {
        setStorage(WECHAT_OPENID_KEY, payload.device_token)
      }
      this.setData({
        wechatSubscribeStatus: '已绑定',
        wechatOpenidBound: Boolean(payload.device_token),
        wechatLastBindMessage: payload.message || '微信订阅消息设备已绑定。',
        wechatSubscriptionAdvice: this.buildSubscriptionAdvice(),
      })
      await this.refreshDeviceStatus()
      return { ok: true, rebound: true }
    } catch (error) {
      console.error('bindWechatSubscription failed', error)
      this.setData({
        wechatSubscribeStatus: '绑定失败',
        wechatOpenidBound: false,
        wechatSubscriptionAdvice: this.buildSubscriptionAdvice(),
        error: '绑定微信订阅消息失败，请检查后端地址、模板状态或重新授权。',
      })
      return { ok: false, reason: 'bind_failed' }
    } finally {
      this.setData({ wechatBinding: false })
    }
  },

  requestWechatSubscription(templateId) {
    return new Promise((resolve, reject) => {
      wx.requestSubscribeMessage({
        tmplIds: [templateId],
        success: (res) => resolve(res[templateId] || 'unknown'),
        fail: reject,
      })
    })
  },

  fetchWechatLoginCode() {
    return new Promise((resolve, reject) => {
      wx.login({
        timeout: 15000,
        success: (res) => {
          if (res.code) {
            resolve(res.code)
            return
          }
          reject(new Error('wx.login 未返回 code'))
        },
        fail: reject,
      })
    })
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
      const subscription = await this.ensureFreshWechatSubscription({ forcePrompt: true, reason: 'test_notification' })
      if (!subscription.ok) {
        this.setData({ error: '本次测试通知未获得新的订阅授权，已取消发送。' })
        return
      }
      await apiRequest({
        url: '/notifications/test',
        method: 'POST',
        data: {
          title: 'DocMind 小程序调试通知',
          body: '这是一条移动端调试通知，用于验证通知链路是否打通。',
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

  async refreshDocumentsWithBusinessSubscription() {
    const shouldPrompt = this.shouldPromptSubscriptionAgain()
    if (shouldPrompt) {
      await this.prepareBusinessNotifications({ forcePrompt: false })
    }
    await this.loadDocuments()
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
      this.setData({ error: '搜索失败，请稍后重试。' })
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
    setStorage(WECHAT_OPENID_KEY, '')
    setStorage(WECHAT_SUBSCRIPTION_STATE_KEY, '')
    wx.redirectTo({ url: '/pages/login/index' })
  },
})

const { loginWithPkce, getStorage, extractErrorMessage } = require('../../utils/auth')
const { DEFAULT_API_BASE, fetchBootstrapConfig } = require('../../utils/config')

Page({
  data: {
    username: 'admin_demo',
    password: 'Password123',
    apiBase: DEFAULT_API_BASE,
    loading: false,
    configSaving: false,
    bootstrapLoading: false,
    error: '',
    configMessage: '',
    bootstrapSummary: '',
  },

  onShow() {
    const app = getApp()
    this.setData({
      apiBase: app.globalData.apiBase || DEFAULT_API_BASE,
      configMessage: '',
      bootstrapSummary: '',
    })
    if (getStorage('access_token')) {
      wx.switchTab({ url: '/pages/docs/index' })
    }
  },

  onUsernameInput(event) {
    this.setData({ username: event.detail.value })
  },

  onPasswordInput(event) {
    this.setData({ password: event.detail.value })
  },

  onApiBaseInput(event) {
    this.setData({ apiBase: event.detail.value, configMessage: '', bootstrapSummary: '' })
  },

  saveApiBase() {
    const app = getApp()
    const rawValue = String(this.data.apiBase || '').trim()
    if (!rawValue) {
      this.setData({ configMessage: '请先填写后端地址。' })
      return
    }
    this.setData({ configSaving: true, configMessage: '', bootstrapSummary: '' })
    try {
      const nextConfig = app.setRuntimeConfig({ apiBase: rawValue })
      this.setData({
        apiBase: nextConfig.apiBase,
        configMessage: `已保存：${nextConfig.apiBase}`,
      })
    } catch (error) {
      this.setData({ configMessage: '保存地址失败，请重试。' })
    } finally {
      this.setData({ configSaving: false })
    }
  },

  async bootstrapFromServer() {
    const app = getApp()
    const rawValue = String(this.data.apiBase || '').trim()
    if (!rawValue) {
      this.setData({ configMessage: '请先填写后端地址。' })
      return
    }
    this.setData({ bootstrapLoading: true, configMessage: '', bootstrapSummary: '', error: '' })
    try {
      const bootstrap = await fetchBootstrapConfig(rawValue)
      const nextConfig = app.setRuntimeConfig({
        apiBase: bootstrap.api_base || rawValue,
        wsBase: bootstrap.ws_base || '',
      })
      const miniapp = bootstrap.auth && bootstrap.auth.miniapp ? bootstrap.auth.miniapp : null
      const summary = miniapp && miniapp.ready
        ? '已获取 bootstrap 配置，小程序客户端已就绪。'
        : '已获取 bootstrap 配置，但小程序客户端仍有待补齐项。'
      this.setData({
        apiBase: nextConfig.apiBase,
        configMessage: `已同步：${nextConfig.apiBase}`,
        bootstrapSummary: summary,
      })
    } catch (error) {
      this.setData({ error: extractErrorMessage(error, '获取 bootstrap 配置失败。') })
    } finally {
      this.setData({ bootstrapLoading: false })
    }
  },

  async submit() {
    if (!this.data.username.trim() || !this.data.password.trim()) {
      this.setData({ error: '请输入用户名和密码。' })
      return
    }
    this.setData({ loading: true, error: '' })
    try {
      await loginWithPkce({
        username: this.data.username.trim(),
        password: this.data.password.trim(),
      })
      wx.switchTab({ url: '/pages/docs/index' })
    } catch (error) {
      this.setData({ error: extractErrorMessage(error, '登录失败，请检查账号、密码或后端地址。') })
    } finally {
      this.setData({ loading: false })
    }
  },
})

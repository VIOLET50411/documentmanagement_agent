const { loginWithPkce, getStorage } = require('../../utils/auth')

Page({
  data: {
    username: 'admin_demo',
    password: 'Password123',
    loading: false,
    error: '',
  },

  onShow() {
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

  async submit() {
    if (!this.data.username.trim() || !this.data.password.trim()) {
      this.setData({ error: '请输入用户名和密码' })
      return
    }
    this.setData({ loading: true, error: '' })
    try {
      await loginWithPkce({ username: this.data.username.trim(), password: this.data.password.trim() })
      wx.switchTab({ url: '/pages/docs/index' })
    } catch (error) {
      this.setData({ error: '登录失败，请检查账号或服务状态。' })
    } finally {
      this.setData({ loading: false })
    }
  },
})

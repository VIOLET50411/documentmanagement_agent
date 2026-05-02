const INSTALLATION_ID_KEY = 'docmind_miniapp_installation_id'

function getOrCreateInstallationId() {
  try {
    const existing = wx.getStorageSync(INSTALLATION_ID_KEY)
    if (existing) return existing
  } catch (error) {
    console.error('read installation id failed', error)
  }

  const nextId = `miniapp-debug-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  try {
    wx.setStorageSync(INSTALLATION_ID_KEY, nextId)
  } catch (error) {
    console.error('save installation id failed', error)
  }
  return nextId
}

function buildMiniappDebugDeviceProfile() {
  const app = getApp()
  let deviceName = '微信小程序'
  try {
    const info = wx.getSystemInfoSync()
    const model = String(info.model || '').trim()
    const platform = String(info.platform || '').trim()
    if (model || platform) {
      deviceName = [model, platform].filter(Boolean).join(' / ')
    }
  } catch (error) {
    console.error('getSystemInfoSync failed', error)
  }

  return {
    platform: 'miniapp-debug',
    device_token: getOrCreateInstallationId(),
    device_name: deviceName,
    app_version: app.globalData.appVersion || 'miniapp-unknown',
  }
}

module.exports = {
  INSTALLATION_ID_KEY,
  getOrCreateInstallationId,
  buildMiniappDebugDeviceProfile,
}

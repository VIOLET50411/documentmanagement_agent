const API_BASE_KEY = 'docmind_api_base'
const WS_BASE_KEY = 'docmind_ws_base'
const BOOTSTRAP_CACHE_KEY = 'docmind_bootstrap_cache'
const DEFAULT_API_BASE = 'http://172.20.10.3:18000/api/v1'

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '')
}

function ensureHttpBase(value) {
  const normalized = trimTrailingSlash(value)
  if (!normalized) return DEFAULT_API_BASE
  if (/^https?:\/\//.test(normalized)) return normalized
  return `https://${normalized}`
}

function buildWsBase(apiBase) {
  const normalized = ensureHttpBase(apiBase)
  if (normalized.startsWith('https://')) {
    return normalized.replace(/^https:\/\//, 'wss://') + '/ws/chat'
  }
  return normalized.replace(/^http:\/\//, 'ws://') + '/ws/chat'
}

function readStorage(key) {
  try {
    return wx.getStorageSync(key)
  } catch (error) {
    return ''
  }
}

function resolveRuntimeConfig() {
  const configuredApiBase = readStorage(API_BASE_KEY) || DEFAULT_API_BASE
  const configuredWsBase = readStorage(WS_BASE_KEY)
  const apiBase = ensureHttpBase(configuredApiBase)
  const wsBase = configuredWsBase ? trimTrailingSlash(configuredWsBase) : buildWsBase(apiBase)
  return { apiBase, wsBase }
}

function persistRuntimeConfig({ apiBase, wsBase }) {
  const normalizedApiBase = ensureHttpBase(apiBase)
  const normalizedWsBase = wsBase ? trimTrailingSlash(wsBase) : buildWsBase(normalizedApiBase)
  wx.setStorageSync(API_BASE_KEY, normalizedApiBase)
  wx.setStorageSync(WS_BASE_KEY, normalizedWsBase)
  return { apiBase: normalizedApiBase, wsBase: normalizedWsBase }
}

function buildBootstrapUrl(value) {
  const normalizedApiBase = ensureHttpBase(value)
  const root = normalizedApiBase.endsWith('/api/v1')
    ? normalizedApiBase.slice(0, -('/api/v1'.length))
    : normalizedApiBase
  return `${trimTrailingSlash(root)}/api/v1/auth/mobile/bootstrap`
}

function fetchBootstrapConfig(value) {
  const bootstrapUrl = buildBootstrapUrl(value)
  return new Promise((resolve, reject) => {
    wx.request({
      url: bootstrapUrl,
      method: 'GET',
      timeout: 15000,
      success: (response) => {
        if (response.statusCode >= 200 && response.statusCode < 300 && response.data) {
          try {
            wx.setStorageSync(BOOTSTRAP_CACHE_KEY, response.data)
          } catch (error) {
            console.error('bootstrap cache save failed', error)
          }
          resolve(response.data)
          return
        }
        reject(new Error(`bootstrap 请求失败（${response.statusCode}）`))
      },
      fail: (error) => {
        reject(new Error(error && error.errMsg ? error.errMsg : 'bootstrap 请求失败'))
      },
    })
  })
}

function getCachedBootstrap() {
  try {
    return wx.getStorageSync(BOOTSTRAP_CACHE_KEY) || null
  } catch (error) {
    return null
  }
}

module.exports = {
  API_BASE_KEY,
  WS_BASE_KEY,
  BOOTSTRAP_CACHE_KEY,
  DEFAULT_API_BASE,
  resolveRuntimeConfig,
  persistRuntimeConfig,
  buildWsBase,
  buildBootstrapUrl,
  fetchBootstrapConfig,
  getCachedBootstrap,
}

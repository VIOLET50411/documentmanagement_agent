function getStorage(key) {
  try {
    return wx.getStorageSync(key)
  } catch (error) {
    return ''
  }
}

function setStorage(key, value) {
  wx.setStorageSync(key, value)
}

function clearAuthState() {
  try {
    wx.removeStorageSync('access_token')
    wx.removeStorageSync('refresh_token')
  } catch (error) {
    console.error('clear auth storage failed', error)
  }
}

function redirectToLogin(reason) {
  clearAuthState()
  const message = encodeURIComponent(reason || '登录状态已失效，请重新登录。')
  try {
    wx.reLaunch({ url: `/pages/login/index?reason=${message}` })
  } catch (error) {
    console.error('redirectToLogin failed', error)
  }
}

function getApiBase() {
  const app = getApp()
  return app.globalData.apiBase
}

function extractErrorMessage(payload, fallback) {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  if (payload instanceof Error && payload.message) return payload.message
  if (typeof payload.statusCode === 'number') return `请求失败：${payload.statusCode}`
  if (payload.data && typeof payload.data.detail === 'string') return payload.data.detail
  if (payload.errMsg) return payload.errMsg
  return fallback
}

function requestWithAuth(options) {
  const token = getStorage('access_token')
  return new Promise((resolve, reject) => {
    wx.request({
      timeout: 15000,
      ...options,
      header: {
        Authorization: token ? `Bearer ${token}` : '',
        'Content-Type': 'application/json',
        ...(options.header || {}),
      },
      success: (response) => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response)
          return
        }
        if (response.statusCode === 401) {
          refreshAccessToken()
            .then((tokenPayload) => {
              const nextToken = tokenPayload && tokenPayload.access_token
              wx.request({
                timeout: 15000,
                ...options,
                header: {
                  Authorization: nextToken ? `Bearer ${nextToken}` : '',
                  'Content-Type': 'application/json',
                  ...(options.header || {}),
                },
                success: (retryResponse) => {
                  if (retryResponse.statusCode >= 200 && retryResponse.statusCode < 300) {
                    resolve(retryResponse)
                    return
                  }
                  console.error('requestWithAuth retry failed', options.url, retryResponse)
                  reject(new Error(extractErrorMessage(retryResponse, '认证刷新后重试失败')))
                },
                fail: (retryError) => {
                  console.error('requestWithAuth retry timeout/fail', options.url, retryError)
                  reject(new Error(extractErrorMessage(retryError, '认证刷新后请求失败')))
                },
              })
            })
            .catch((refreshError) => {
              console.error('refreshAccessToken failed', refreshError)
              redirectToLogin(extractErrorMessage(refreshError, '登录状态已失效，请重新登录。'))
              reject(new Error(extractErrorMessage(refreshError, '刷新登录状态失败')))
            })
          return
        }
        console.error('requestWithAuth failed', options.url, response)
        if (response.statusCode === 401) {
          redirectToLogin('登录状态已失效，请重新登录。')
        }
        reject(new Error(extractErrorMessage(response, '请求失败')))
      },
      fail: (error) => {
        console.error('requestWithAuth timeout/fail', options.url, error)
        reject(new Error(extractErrorMessage(error, '请求超时或网络不可用')))
      },
    })
  })
}

function refreshAccessToken() {
  const refreshToken = getStorage('refresh_token')
  if (!refreshToken) {
    return Promise.reject(new Error('missing_refresh_token'))
  }
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBase()}/auth/mobile/token`,
      method: 'POST',
      timeout: 15000,
      data: {
        grant_type: 'refresh_token',
        client_id: 'docmind-miniapp',
        refresh_token: refreshToken,
      },
      success: (tokenRes) => {
        if (tokenRes.statusCode >= 200 && tokenRes.statusCode < 300 && tokenRes.data && tokenRes.data.access_token) {
          setStorage('access_token', tokenRes.data.access_token)
          setStorage('refresh_token', tokenRes.data.refresh_token || refreshToken)
          resolve(tokenRes.data)
          return
        }
        console.error('refresh token exchange failed', tokenRes)
        reject(new Error(extractErrorMessage(tokenRes, '刷新令牌失败')))
      },
      fail: (error) => {
        console.error('refresh token request failed', error)
        reject(new Error(extractErrorMessage(error, '刷新令牌请求失败')))
      },
    })
  })
}

function loginWithPkce({ username, password }) {
  const verifier = `miniapp-${Date.now()}`
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBase()}/auth/mobile/authorize`,
      method: 'POST',
      timeout: 15000,
      data: {
        username,
        password,
        client_id: 'docmind-miniapp',
        redirect_uri: 'https://servicewechat.com/docmind/callback',
        code_challenge: verifier,
        code_challenge_method: 'plain',
        scope: 'openid profile email offline_access',
      },
      success: (authorizeRes) => {
        const code = authorizeRes.data && authorizeRes.data.code
        if (!code) {
          console.error('authorize failed', authorizeRes)
          reject(new Error(extractErrorMessage(authorizeRes, '移动授权失败')))
          return
        }
        wx.request({
          url: `${getApiBase()}/auth/mobile/token`,
          method: 'POST',
          timeout: 15000,
          data: {
            grant_type: 'authorization_code',
            code,
            client_id: 'docmind-miniapp',
            redirect_uri: 'https://servicewechat.com/docmind/callback',
            code_verifier: verifier,
          },
          success: (tokenRes) => {
            if (tokenRes.data && tokenRes.data.access_token) {
              setStorage('access_token', tokenRes.data.access_token)
              setStorage('refresh_token', tokenRes.data.refresh_token || '')
              resolve(tokenRes.data)
              return
            }
            console.error('token exchange failed', tokenRes)
            reject(new Error(extractErrorMessage(tokenRes, '令牌交换失败')))
          },
          fail: (error) => {
            console.error('token request failed', error)
            reject(new Error(extractErrorMessage(error, '令牌请求失败')))
          },
        })
      },
      fail: (error) => {
        console.error('authorize request failed', error)
        reject(new Error(extractErrorMessage(error, '移动授权请求失败')))
      },
    })
  })
}

module.exports = {
  getStorage,
  setStorage,
  requestWithAuth,
  loginWithPkce,
  refreshAccessToken,
  extractErrorMessage,
  clearAuthState,
  redirectToLogin,
}

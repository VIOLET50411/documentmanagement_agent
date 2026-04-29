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

function getApiBase() {
  const app = getApp()
  return app.globalData.apiBase
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
        console.error('requestWithAuth failed', options.url, response)
        reject(response)
      },
      fail: (error) => {
        console.error('requestWithAuth timeout/fail', options.url, error)
        reject(error)
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
          reject(authorizeRes)
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
            reject(tokenRes)
          },
          fail: (error) => {
            console.error('token request failed', error)
            reject(error)
          },
        })
      },
      fail: (error) => {
        console.error('authorize request failed', error)
        reject(error)
      },
    })
  })
}

module.exports = { getStorage, setStorage, requestWithAuth, loginWithPkce }

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
                  reject(retryResponse)
                },
                fail: (retryError) => {
                  console.error('requestWithAuth retry timeout/fail', options.url, retryError)
                  reject(retryError)
                },
              })
            })
            .catch((refreshError) => {
              console.error('refreshAccessToken failed', refreshError)
              reject(response)
            })
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
        reject(tokenRes)
      },
      fail: (error) => {
        console.error('refresh token request failed', error)
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

module.exports = { getStorage, setStorage, requestWithAuth, loginWithPkce, refreshAccessToken }

const { requestWithAuth } = require('./auth')

function apiRequest({ url, method = 'GET', data = null }) {
  const app = getApp()
  return requestWithAuth({
    url: `${app.globalData.apiBase}${url}`,
    method,
    data,
  })
}

module.exports = { apiRequest }

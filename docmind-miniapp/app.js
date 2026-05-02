const { resolveRuntimeConfig, persistRuntimeConfig } = require('./utils/config')

App({
  globalData: {
    ...resolveRuntimeConfig(),
    appVersion: 'miniapp-0.1.0',
  },

  onLaunch() {
    this.globalData = {
      ...this.globalData,
      ...resolveRuntimeConfig(),
    }
  },

  setRuntimeConfig(config) {
    const nextConfig = persistRuntimeConfig(config)
    this.globalData = {
      ...this.globalData,
      ...nextConfig,
    }
    return nextConfig
  },
})

function connectChatSocket({ token, onMessage, onOpen, onClose }) {
  const app = getApp()
  const socket = wx.connectSocket({
    url: app.globalData.wsBase,
  })

  socket.onOpen(() => {
    socket.send({ data: JSON.stringify({ type: 'auth', token }) })
    if (onOpen) onOpen()
  })

  socket.onMessage((event) => {
    const payload = JSON.parse(event.data || '{}')
    if (onMessage) onMessage(payload, socket)
  })

  socket.onClose(() => {
    if (onClose) onClose()
  })

  return socket
}

module.exports = { connectChatSocket }

# DocMind Miniapp Scaffold

## 已接通的能力
- WebSocket 聊天入口：`/api/v1/ws/chat`
- 移动 OAuth2/PKCE：`/api/v1/auth/mobile/*`
- 文档页占位：后续可接文档检索、上传状态、推送结果

## 当前约束
- 小程序示例使用 `plain` PKCE，便于端内直接跑通
- 推送通知在小程序侧仍需接微信订阅消息能力，本轮先完成后端注册/测试/审计闭环
- `app.js` 中的 `apiBase` / `wsBase` 需要按真实部署地址调整

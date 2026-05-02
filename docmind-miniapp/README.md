# DocMind Miniapp Scaffold

## 已接通的能力
- WebSocket 聊天入口：`/api/v1/ws/chat`
- 移动 OAuth2/PKCE：`/api/v1/auth/mobile/*`
- 文档页占位：后续可接文档检索、上传状态、推送结果

## 当前约束
- 小程序示例使用 `plain` PKCE，便于端内直接跑通
- 推送通知在小程序侧仍需接微信订阅消息能力，本轮先完成后端注册/测试/审计闭环

## 最新接入方式
- 登录页支持直接保存后端地址，无需每次手改 `app.js`
- 默认会根据 `apiBase` 自动推导 `wsBase`
- 登录页支持调用 `/api/v1/auth/mobile/bootstrap` 自动探测 `apiBase/wsBase`
- 推荐填写形如 `https://your-domain/api/v1` 的地址

## 微信小程序后台配置
- `request` 合法域名：填写你的 HTTPS 后端域名
- `socket` 合法域名：填写同一域名的 `wss://` 地址
- 若仍使用本地联调地址，需通过可公网访问的 HTTPS/WSS 代理中转，`localhost` 与裸内网 IP 不能直接作为正式合法域名

## 推荐调试顺序
1. 在登录页填写后端地址
2. 点击“自动探测”，确认后端返回 bootstrap 成功
3. 再执行登录，避免手工拼接地址或路径漂移

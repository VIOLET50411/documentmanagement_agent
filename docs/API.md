# DocMind Agent API

## Base

- Base URL: `/api/v1`
- 健康检查: `GET /health`

## 鉴权

### `POST /auth/register`
邀请制注册（默认关闭公开注册）。

### `POST /auth/login`
登录并返回 `access_token` + `refresh_token`。

### `POST /auth/refresh`
刷新访问令牌。

### `GET /auth/me`
获取当前登录用户信息。

### `POST /auth/invite`
管理员发送邀请。

### `GET /auth/invitations`
管理员查询邀请记录（支持分页）。

### `POST /auth/invite/{invitation_id}/resend`
重发邀请。

### `POST /auth/invite/{invitation_id}/revoke`
撤销邀请。

### `POST /auth/send-verification-code`
发送邮箱验证码（本地环境写入 outbox）。

### `POST /auth/verify-email`
验证邮箱验证码。

### `POST /auth/password-reset/request`
发起密码重置。

### `POST /auth/password-reset/confirm`
确认重置密码。

## 聊天

### `POST /chat/stream`
SSE 流式问答。

请求体示例：

```json
{
  "message": "公司年假制度是什么样的？",
  "thread_id": null,
  "search_type": "hybrid"
}
```

事件类型：

- `thinking`
- `searching`
- `reading`
- `tool_call`
- `streaming`
- `done`
- `error`

### `GET /chat/history`
按 `thread_id` 查询会话历史。

### `POST /chat/feedback`
提交消息反馈，参数：`message_id`、`rating`、`correction`。

## 文档

### `POST /documents/upload`
上传文档并启动异步处理。

支持类型：`PDF/DOCX/XLSX/CSV/PNG/JPEG`。

### `GET /documents/`
分页查询文档列表（支持 `page/size/department/status`）。

### `GET /documents/{doc_id}/status`
查询文档处理状态与进度。

### `GET /documents/{doc_id}/events`
查询最近处理事件（阶段日志）。

### `POST /documents/{doc_id}/retry`
重试文档处理任务。

### `DELETE /documents/{doc_id}`
删除文档及关联索引数据（异步删除派生索引）。

## 检索

### `GET /search/`
直接检索（绕过 Agent），参数：

- `q`
- `top_k`
- `search_type` (`hybrid|vector|keyword|graph`)

## 管理台

### `GET /admin/users`
租户用户列表（`ADMIN`）。

### `GET /admin/analytics/overview`
管理台总览数据。

### `GET /admin/pipeline/status`
管线状态汇总（active/queued/failed/completed）。

### `GET /admin/pipeline/jobs`
任务列表（支持 `limit/offset/status`）。

### `POST /admin/pipeline/{doc_id}/retry`
重试单个任务。

### `POST /admin/pipeline/retry-failed`
批量重试失败任务。

### `GET /admin/pipeline/failure-summary`
失败原因聚合（错误签名）。

### `POST /admin/pipeline/retry-by-signature`
按错误签名批量重试。

### `GET /admin/security/events`
安全审计事件列表（支持筛选 `severity/action/result/from/to`）。

### `GET /admin/system/backends`
后端组件状态：ES/Milvus/Neo4j/Redis/ClamAV/LLM（Ollama）。

### `GET /admin/system/retrieval-metrics`
检索后端可观测指标（成功率/错误率/超时率/P95）。

### `GET /admin/system/readiness`
平台就绪度评分。

### `GET /admin/system/retrieval-integrity`
检索一致性健康检查（PG/ES/Milvus/Neo4j 对齐 + 样本回查）。

### `POST /admin/evaluation/run`
运行离线评估（fallback）。

### `GET /admin/evaluation/latest`
读取最新离线评估报告。

### `GET /admin/evaluation/runtime-metrics`
读取运行时评估指标。

### `GET /admin/evaluation/runtime-metrics/history`
读取运行时指标历史。

### `GET /admin/evaluation/runtime-metrics/export`
导出运行时指标（`csv/json`）。

### `POST /admin/reindex`
重建租户索引。

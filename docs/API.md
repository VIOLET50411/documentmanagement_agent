# DocMind Agent API 概览

## 1. 基本信息

- API 前缀：`/api/v1`
- 健康检查：`GET /health`
- OpenAPI：`GET /docs`

当前本地 Docker 默认访问地址：

- 后端：`http://localhost:18000`
- 前端：`http://localhost:15173`

## 2. 认证接口

### `/auth`

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/invite`
- `GET /api/v1/auth/invitations`
- `POST /api/v1/auth/invite/{invitation_id}/resend`
- `POST /api/v1/auth/invite/{invitation_id}/revoke`
- `POST /api/v1/auth/send-verification-code`
- `POST /api/v1/auth/verify-email`
- `POST /api/v1/auth/password-reset/request`
- `POST /api/v1/auth/password-reset/confirm`

移动端认证入口：

- `POST /api/v1/auth/mobile/authorize`
- `POST /api/v1/auth/mobile/token`
- `GET /api/v1/auth/mobile/userinfo`

## 3. 文档接口

### `/documents`

- `POST /api/v1/documents/upload`
- `POST /api/v1/documents/upload/session`
- `POST /api/v1/documents/upload/chunk`
- `POST /api/v1/documents/upload/complete`
- `GET /api/v1/documents/`
- `GET /api/v1/documents/{doc_id}/status`
- `GET /api/v1/documents/{doc_id}/events`
- `POST /api/v1/documents/{doc_id}/retry`
- `DELETE /api/v1/documents/{doc_id}`
- `GET /api/v1/documents/{doc_id}/download`

说明：

- 支持普通上传和分片上传
- 上传前会做类型、大小和安全扫描校验

## 4. 检索与问答接口

### 搜索

- `GET /api/v1/search/`

常用参数：

- `q`
- `top_k`
- `search_type=hybrid|vector|keyword|graph`
- `mode=hybrid|vector|keyword|graph`

### 聊天

- `POST /api/v1/chat/stream`
- `POST /api/v1/chat/message`
- `GET /api/v1/chat/history`
- `POST /api/v1/chat/feedback`

`/chat/stream` 为 SSE 主入口，当前运行时会输出状态事件和最终答案。

## 5. 管理端接口

### 文档治理

- `GET /api/v1/admin/documents/tasks`
- `POST /api/v1/admin/documents/tasks/{task_id}/retry`
- `POST /api/v1/admin/documents/reindex`

### 系统与检索

- `GET /api/v1/admin/system/backends`
- `GET /api/v1/admin/system/readiness`
- `GET /api/v1/admin/system/retrieval-metrics`
- `GET /api/v1/admin/system/gap-report`
- `GET /api/v1/admin/system/security-policy`
- `GET /api/v1/admin/system/mobile-auth`
- `GET /api/v1/admin/system/push-notifications`

### Runtime

- `GET /api/v1/admin/runtime/tasks`
- `GET /api/v1/admin/runtime/metrics`
- `GET /api/v1/admin/runtime/tool-decisions`
- `GET /api/v1/admin/runtime/tool-decisions/summary`
- `POST /api/v1/admin/runtime/replay`

### 安全

- `GET /api/v1/admin/security/events`
- `GET /api/v1/admin/security/alerts`
- `GET /api/v1/admin/security/summary`
- `POST /api/v1/admin/security/watermark/trace`

### 评估

- `POST /api/v1/admin/evaluation/run`
- `POST /api/v1/admin/evaluation/run-async`
- `GET /api/v1/admin/evaluation/tasks/{task_id}`
- `GET /api/v1/admin/evaluation/latest`
- `GET /api/v1/admin/evaluation/history`
- `GET /api/v1/admin/evaluation/gate-summary`
- `GET /api/v1/admin/evaluation/runtime-metrics`
- `GET /api/v1/admin/evaluation/runtime-metrics/history`
- `GET /api/v1/admin/evaluation/runtime-metrics/export`

### 训练与语料

- `GET /api/v1/admin/llm/domain-config`
- `POST /api/v1/admin/llm/domain-corpus/export`
- `GET /api/v1/admin/llm/public-corpus/latest`
- `POST /api/v1/admin/llm/public-corpus/export-async`
- `POST /api/v1/admin/llm/training/run-async`
- `GET /api/v1/admin/llm/training/jobs`
- `GET /api/v1/admin/llm/training/jobs/{job_id}`
- `GET /api/v1/admin/llm/models`
- `POST /api/v1/admin/llm/models/{model_id}/activate`

## 6. 使用建议

- 对实际字段和请求体，以当前 `/docs` 中 OpenAPI 为准
- 对当前功能范围和约束，以 `docs/ARCHITECTURE.md` 与 `docs/IMPLEMENTATION_PLAN.md` 为准
- 对尚未接入真实 AI 的接口行为，以 `docs/AI_API_PLACEHOLDERS.md` 为准

# DocMind Agent

DocMind Agent 是一个面向企业文档场景的文档管理与问答平台。当前仓库已经具备可运行的上传、入库、检索、流式问答、管理后台和运行时治理主链路，重点不再是“搭骨架”，而是持续把文档 Agent 做得更稳、更准、更好用。

## 当前状态

- 后端、前端、基础设施均已接入 Docker Compose 本地开发栈
- 文档上传、分片上传、解析、切块、索引、状态回写已打通
- 检索链路已接入 Elasticsearch、Milvus、Neo4j，并保留 fallback
- Runtime V2、SSE、Replay、Checkpoint、Resume 已是主链路
- 管理端已覆盖系统状态、检索指标、安全审计、评估、训练编排等入口
- 最近一轮核心验证已通过，当前应以“质量增强”而不是“补齐空壳”为主

## 目录结构

```text
.
├─ backend/                  FastAPI、Celery、检索与 Agent Runtime
├─ frontend/                 Vue 3 + Vite Web 客户端
├─ docs/                     当前有效的项目说明文档
├─ datasets/                 共享数据集与语料
├─ reports/                  评估、交付、训练等产物
├─ scripts/                  预检、重建、验证脚本
├─ docker-compose.yml        基础设施服务
└─ docker-compose.dev.yml    应用服务与开发挂载
```

## 本地默认端口

以当前 Docker 运行配置为准：

- 前端：`http://localhost:15173`
- 后端：`http://localhost:18000`
- 后端 OpenAPI：`http://localhost:18000/docs`
- Flower：`http://localhost:15555`
- Ollama：`http://localhost:11434`
- MinIO Console：`http://localhost:9001`

## 快速启动

默认面向两种使用方式：

- Web / Docker 本地开发：开箱可跑，不依赖你自己的 Firebase 项目
- Android / 推送联调：需要额外补自己的 Firebase 和移动端配置

1. 准备环境变量：

```powershell
Copy-Item .env.example .env
```

2. 启动完整栈：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

3. 可选：拉取默认 Ollama 模型：

```powershell
docker exec docmind-ollama ollama pull qwen2.5:1.5b
docker exec docmind-ollama ollama pull nomic-embed-text
```

4. 健康检查：

```powershell
Invoke-RestMethod http://localhost:18000/health
```

5. 打开前端并登录：

- 前端：`http://localhost:15173`
- 默认演示账号：`admin_demo`
- 默认演示密码：`Password123`

以上演示口令仅用于本地开发和验收，不可直接用于生产环境。

## 公共仓库使用说明

- 仓库不会提交真实 `.env`、`secrets/`、Firebase service account 或 Android `google-services.json`
- Web 主链路可在未配置 Firebase 的情况下正常启动和验证
- 如需 Android 推送能力，请参考 [本地环境与脱敏配置指南](docs/LOCAL_SETUP.md)
- 如需完整部署与验收，请继续阅读 [部署说明](docs/DEPLOYMENT.md) 和 [交付运行手册](docs/DELIVERY_RUNBOOK.md)

## 当前能力边界

已经稳定可用：

- JWT 登录、刷新、邀请注册、邮箱验证、密码重置
- 多租户隔离、RBAC、审计与基础安全拦截
- 文档上传、分片上传、处理进度、失败重试、原文访问
- 关键词 / 向量 / 图谱 / 混合检索
- SSE 聊天、会话历史、反馈提交
- 管理端运行时、评估、训练、系统健康入口

仍在持续增强：

- 中文文档场景下的真实召回率与追问能力
- 摘要、合规、制度问答等文档 Agent 专项能力
- 高保真 OCR、复杂版面理解、复杂表格抽取
- 真实生产级模型训练、灰度和自动发布闭环

## 常用验证

后端测试：

```powershell
Set-Location backend
py -3 -m pytest -q
```

前端构建：

```powershell
Set-Location frontend
npm.cmd run build
```

交付预检：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-preflight.ps1
```

## 文档入口

- [项目文档索引](docs/DOC_INDEX.md)
- [本地环境与脱敏配置指南](docs/LOCAL_SETUP.md)
- [架构说明](docs/ARCHITECTURE.md)
- [需求规格](docs/REQUIREMENTS_SPEC.md)
- [实施计划](docs/IMPLEMENTATION_PLAN.md)
- [文档 Agent 路线图](docs/DOCUMENT_AGENT_ROADMAP.md)
- [API 说明](docs/API.md)
- [部署说明](docs/DEPLOYMENT.md)
- [交付运行手册](docs/DELIVERY_RUNBOOK.md)
- [AI 占位边界](docs/AI_API_PLACEHOLDERS.md)

## 维护约束

- 中文文案、提示词、注释、说明文档统一按 UTF-8 维护
- 发现乱码时，优先视为编码异常处理，不继续传播
- 项目已挂载到 Docker 容器，改动影响运行路径时要同步到容器并验证

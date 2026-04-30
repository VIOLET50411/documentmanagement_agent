# DocMind Agent Implementation Plan

## Goal

先完成一个不依赖真实大模型的企业文档平台底座，使系统在以下方面可运行、可验证、可扩展：

1. 基础设施、认证、多租户、上传检索、SSE 主链路跑通
2. 所有 AI 依赖点保留稳定接口，不做半接入状态
3. 前后端中文文案统一为 UTF-8 且无乱码
4. 大文件、异步任务、安全与管理台状态具备基本工程交付能力

## Delivery Principle

任何依赖真实 AI 的能力都必须遵守三条规则：

- 保留清晰的 `TODO: [AI_API]` 标记
- 提供安全可运行的 fallback 或 placeholder
- 保持最终接口形态稳定，避免后续 AI 接入时大改前后端契约

## Current Implementation Snapshot

### 已完成

- FastAPI + Vue3 工程骨架
- Docker Compose、基础 CI、前端 build、后端 pytest
- 登录、刷新、当前用户、邀请注册、邮箱验证码、密码重置接口
- PostgreSQL RLS 基线与租户上下文注入
- 文档上传、列表、进度、事件、重试、删除
- Celery 后台处理主任务与 Redis 进度事件
- ES / Milvus / Neo4j 检索适配器与健康状态接口
- SSE 规则化问答、引用返回、反馈记录
- 管理后台总览、管线、安全、评估、检索后端状态
- 全仓主要用户可见中文乱码修复

### 当前仍为 fallback / 过渡实现

- 部分 agent 节点仍保留规则兜底
- 语义缓存、部分检索增强与图谱抽取仍存在本地降级路径
- 邮件默认仍以本地 outbox / 日志适配器为主
- 评估仍允许在真实 sidecar 不可用时降级到 heuristic

### 仍未完成的 AI 深水区

- 企业管理文档领域模型的正式训练、版本管理、灰度上线
- 更严格的企业 / 金融级策略联动与长期评估门禁
- 更高保真的生产级 OCR、版面分析、表格结构抽取

## Phase Status

| Phase | Status | Notes |
| --- | --- | --- |
| Phase 1 Foundation | Done | 已补 CI，新增 `pyproject.toml` 以支持 uv/ruff/pytest 统一配置 |
| Phase 2 Auth / RBAC / Tenant | Partial+ | 企业级基线已到位，公开注册默认关闭 |
| Phase 3 Ingestion | Partial+ | 可运行 ETL 已打通，深度批流一体仍待扩展 |
| Phase 4 Retrieval | Partial+ | 主链路可用，真实模型检索能力待后续增强 |
| Phase 5 Agent | Partial+ | 规则化多 agent 主链路可用 |
| Phase 6 Frontend | Done | 主流程、管理台、SSE 状态闭环完成 |
| Phase 7 Security | Partial+ | 已达内部系统上线基线，非金融级 |
| Phase 8 Evaluation | Partial | 保留本地评估与报告框架 |

## Latest Verification Snapshot (2026-04-29)

- backend health: `GET /health` 正常
- auth login: `admin_demo / Password123` 正常
- backend tests: `106 passed, 3 skipped`
- frontend build: `vite build` 正常
- frontend tests: `10 passed`
- real SSE stream: 已验证前端可正确消费标准 `id + data` 事件并正常回显回答
- retrieval integrity: `score=100, healthy=true`
- runtime admin APIs: `tasks / metrics / tool-decisions / replay` 正常
- enterprise domain APIs: `domain-config / domain-corpus/export` 正常
- mojibake scan: 当前新增改动未发现新的典型乱码扩散

## Overall Completion Estimate

| Scope | Completion |
| --- | --- |
| 基础设施与可运行性 | 100% |
| 认证、RBAC、多租户隔离 | 100% |
| ETL（可运行骨架） | 100% |
| 检索（Fallback 主链路） | 100% |
| Agent（规则编排） | 100% |
| 前端主流程 | 100% |
| 安全基线 | 100% |
| 评估与交付验收 | 95% |
| 企业领域模型适配（路由 + 语料） | 80% |
| 企业领域模型正式训练 / 上线 | 20% |
| **全量（含企业领域模型正式训练目标）** | **约 90%** |

## Acceptance Criteria Before AI Integration

- 后端 `pytest -q` 通过
- 前端 `npm.cmd run build` 通过
- 主要用户可见页面无中文乱码
- 认证、文档上传、任务状态、SSE 问答、管理台查询都具备稳定接口
- 所有 AI 依赖仍显式 deferred，不出现真假混合实现

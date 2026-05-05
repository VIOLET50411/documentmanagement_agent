# DocMind 系统设计说明书

## 1. 文档说明

### 1.1 编写目的

本文档用于说明 DocMind 平台的总体架构、模块划分、关键链路、存储设计、接口设计、部署方式、安全基线和运行边界，作为系统实现、联调、测试和答辩说明的技术依据。

### 1.2 设计原则

1. 先保证主链路可运行，再逐步提升真实 AI 覆盖率。
2. 真实能力可接入，但必须保留可观测、可降级的 fallback。
3. 通过模块化分层降低前后端、运行时和外部依赖之间的耦合。
4. 通过租户隔离、角色鉴权和安全审计保证基本交付安全线。

## 2. 总体架构

系统整体采用前后端分离加异步任务处理架构，核心组件如下：

1. 前端展示层：Vue 3 + Vite，负责登录、文档中心、知识检索、智能问答、任务中心、平台管理和个人设置页面。
2. API 服务层：FastAPI，负责认证、权限、文档接口、检索接口、聊天接口、管理接口和健康检查。
3. 运行时编排层：Agent Runtime V2，负责问答请求的任务化执行、工具决策、事件流输出、trace 和 replay。
4. 文档处理层：Celery 异步任务链，负责文档解析、切块、向量化、索引写入和状态回写。
5. 检索层：Elasticsearch、Milvus、Neo4j 与 PostgreSQL 共同构成多通道检索基础。
6. 存储与基础设施层：PostgreSQL、Redis、MinIO 以及 Docker Compose 编排的各类 sidecar。

## 3. 逻辑架构设计

### 3.1 前端模块

根据路由设计，前端主要页面包括：

- `/login`：登录页。
- `/chat`：智能问答页。
- `/tasks`：任务中心，管理员可见。
- `/documents`：文档中心。
- `/search`：知识检索页。
- `/admin`：平台管理页，管理员可见。
- `/settings`：个人设置页。

前端使用鉴权状态判断是否允许访问受保护路由，并按角色控制管理员页面显示。

### 3.2 后端 API 模块

后端主要 API 模块包括：

- `auth`：认证与邀请注册。
- `documents`：文档上传、分片上传、状态查询、事件查询、重试和删除。
- `search`：直接检索接口。
- `chat`：SSE 问答与历史、反馈。
- `admin`：系统状态、任务治理、安全审计、运行时和评估接口。
- `ws_chat`：WebSocket 兼容链路。

### 3.3 运行时模块

Runtime V2 是当前唯一生产链路，主要组件包括：

- `engine.py`：统一运行入口。
- `types.py`：运行时请求、状态和事件定义。
- `task_store.py`：运行时任务生命周期管理。
- `tool_registry.py`：工具注册与结果封装。
- `permission_gate.py`：工具权限决策。
- `agent_definitions.py`：内置 Agent 定义与扩展入口。
- checkpoint 相关模块：支持状态持久化和恢复。

### 3.4 文档处理模块

文档处理模块负责以下任务：

1. 文档安全扫描与临时落盘。
2. 原文件写入对象存储。
3. 内容解析。
4. 文本切块。
5. 向量化。
6. 多后端索引写入。
7. 处理进度和状态回写。

## 4. 关键业务流程设计

### 4.1 登录与访问控制流程

1. 用户在前端提交账号密码。
2. 后端验证凭据并返回访问令牌与刷新令牌。
3. 前端保存认证状态，并在路由跳转时检查鉴权。
4. 访问管理员页面时，前端与后端同时校验角色。

### 4.2 文档上传流程

1. 用户发起文件上传或分片上传。
2. 后端校验文件类型、大小限制和安全扫描结果。
3. 后端创建文档记录并把原文件保存到 MinIO。
4. Celery 异步启动解析、切块、向量化和索引任务。
5. Redis 与 PostgreSQL 持续回写进度、事件和最终状态。
6. 前端轮询或查询状态接口，展示 `queued` 到 `ready` 的流转。

### 4.3 智能问答流程

1. 用户在聊天页提交问题。
2. 后端完成 JWT、租户和权限上下文注入。
3. Runtime V2 接管请求并进行任务化执行。
4. 运行时根据策略触发检索、阅读、工具决策和生成节点。
5. 后端通过 SSE 持续返回状态事件和内容事件。
6. 前端按事件类型展示运行过程和最终回答。
7. 会话、引用和反馈被持久化。

### 4.4 管理后台治理流程

1. 管理员查看总览、任务状态和系统后端状态。
2. 当任务失败时，管理员可按单文档、失败签名或失败批次发起重试。
3. 管理员可查看审计事件、检索一致性、运行时指标和评估结果。
4. 管理员可通过 replay 和 checkpoint 摘要追踪问题链路。

## 5. 数据与存储设计

### 5.1 PostgreSQL

PostgreSQL 作为主事实源，负责保存：

- 用户、租户、角色与认证相关数据。
- 文档元数据、状态、错误信息、chunk 元数据。
- 会话历史、消息反馈、审计记录。
- 运行时 checkpoint 和部分管理数据。

### 5.2 Redis

Redis 负责保存：

- 进度状态与阶段事件。
- 运行时任务、trace、replay 数据。
- 缓存、计数器和部分短生命周期状态。
- Embedding 维度探测等快速读写元数据。

### 5.3 MinIO

MinIO 负责保存原始文档和相关对象文件，是文档文件层的主要承载介质。

### 5.4 Elasticsearch

Elasticsearch 负责全文索引和关键词召回。

### 5.5 Milvus

Milvus 负责向量索引和语义召回。

### 5.6 Neo4j

Neo4j 负责实体与关系图谱查询能力。

## 6. 接口设计摘要

### 6.1 认证接口

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`
- 邀请、验证码和密码重置相关接口

### 6.2 文档接口

- `POST /api/v1/documents/upload`
- `POST /api/v1/documents/upload/session`
- `POST /api/v1/documents/upload/chunk`
- `POST /api/v1/documents/upload/complete`
- `GET /api/v1/documents/`
- `GET /api/v1/documents/{doc_id}/status`
- `GET /api/v1/documents/{doc_id}/events`
- `POST /api/v1/documents/{doc_id}/retry`
- `DELETE /api/v1/documents/{doc_id}`

### 6.3 检索与问答接口

- `GET /api/v1/search/`
- `POST /api/v1/chat/stream`
- `GET /api/v1/chat/history`
- `POST /api/v1/chat/feedback`

### 6.4 管理接口

- 用户、总览、管线治理、安全审计、后端状态、检索指标、检索一致性。
- Runtime 任务、指标、工具决策、决策汇总、replay、checkpoint。
- 评估运行、结果查询、历史导出。

## 7. SSE 与运行时事件设计

### 7.1 事件类型

当前 SSE 问答链路至少覆盖以下事件类型：

- `thinking`
- `searching`
- `reading`
- `tool_call`
- `streaming`
- `done`
- `error`

### 7.2 兼容字段

为支持追踪与恢复，事件中包含以下关键字段：

- `event_id`
- `sequence_num`
- `trace_id`
- `source`
- `degraded`
- `fallback_reason`

### 7.3 Replay 与恢复

系统支持以下恢复方式：

- `resume_trace_id` + `last_sequence`
- 标准 `Last-Event-ID` 头
- 管理员 replay 接口

## 8. 安全设计

### 8.1 身份与权限

1. 采用 JWT 进行身份认证。
2. 采用 RBAC 进行角色鉴权。
3. 采用租户隔离约束数据访问。

### 8.2 上传安全

1. 校验文件类型和大小。
2. 上传前后进行基础安全扫描。
3. 对不符合规则的文件记录审计事件并阻断。

### 8.3 审计与守卫

1. 关键行为写入安全审计事件。
2. 输入输出保留安全守卫扩展点。
3. 可选接入 Guardrails、Presidio、ClamAV 等安全能力。

## 9. 部署设计

### 9.1 本地开发部署

系统默认通过 Docker Compose 启动后端依赖和应用服务。典型组件包括：

- frontend
- backend
- celery worker
- celery beat
- postgres
- redis
- minio
- elasticsearch
- milvus
- neo4j
- 其他 sidecar

### 9.2 混合启动模式

支持基础设施走容器、应用服务本地运行的方式，便于调试前后端。

### 9.3 生产部署方向

建议采用反向代理、应用多副本、独立数据库与缓存、对象存储、向量库和图数据库的独立部署方案，并对 SSE 代理策略进行专项配置。

## 10. 可观测与运维设计

系统当前提供以下运维能力：

1. `/health` 健康检查。
2. 可选 `/metrics` 指标输出。
3. 检索指标与平台就绪度。
4. 检索一致性检查。
5. Runtime 任务与性能指标。
6. 评估结果与历史导出。
7. 任务维护脚本、预检脚本和压测脚本。

## 11. 当前实现边界

### 11.1 已稳定实现的部分

- 前后端主骨架。
- 认证、权限、租户隔离基线。
- 文档上传与异步处理闭环。
- 检索适配器和管理后台基础治理能力。
- Runtime V2、SSE 事件、trace/replay、评估与预检框架。

### 11.2 真实接入与降级共存的部分

- LLM 与 Embedding。
- Reranker。
- OCR 与复杂文档解析。
- 安全 sidecar。
- Ragas 评估。

### 11.3 尚未完全收口的部分

- 更严格的真实模式门禁。
- 更高保真 OCR 与版面理解。
- 真正的生产级灰度发布与流量控制。
- 更细粒度的页面级测试与场景级自动化验证。

## 12. 后续优化方向

1. 细化页面级和接口级设计文档。
2. 扩展组件级、页面级和端到端测试。
3. 缩小 fallback 触发面，提升真实 AI 路径覆盖率。
4. 增强领域数据治理、训练闭环和交付报告体系。

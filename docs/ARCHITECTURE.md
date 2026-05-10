# DocMind Agent 架构说明

## 1. 总览

DocMind Agent 的定位不是通用执行代理，而是企业文档场景下的文档管理、检索、问答和治理平台。当前架构遵循两个核心原则：

1. 主链路必须真实可运行。
2. AI 相关能力允许占位、降级和替换，但不能破坏现有接口与治理。

## 2. 架构分层

### 前端层

- 技术栈：Vue 3、Vite、Pinia、Vue Router、Vitest
- 主要页面：聊天、文档中心、任务状态、系统管理、设置
- 职责：承载上传、检索、SSE 对话、引用展示、反馈和管理视图

### API 与编排层

- 技术栈：FastAPI
- 职责：鉴权、RBAC、租户上下文、上传接口、问答接口、管理接口、事件流输出
- 运行形态：当前后端主服务为 `docmind-backend`

### 文档处理层

- 技术栈：Celery、Redis
- 职责：解析、OCR、切块、向量化、索引同步、任务状态回写
- 运行形态：当前工作进程为 `docmind-celery-worker`

### 检索层

- Elasticsearch：关键词检索
- Milvus：向量检索
- Neo4j：关系检索
- HybridSearcher：统一融合入口

### 数据与存储层

- PostgreSQL：业务事实源
- Redis：缓存、限流、任务态、运行态指标
- MinIO：原始文档对象存储
- Reports / Datasets：评估、训练、数据共享产物

### 治理与侧车层

- ClamAV：文件扫描
- Guardrails sidecar：输入输出安全能力
- Ragas sidecar：评估能力
- Ollama：本地 LLM / Embedding 运行入口

## 3. 核心运行链路

### 文档入库链路

1. 用户上传文档或发起分片上传。
2. 后端完成鉴权、类型校验、大小校验和安全扫描。
3. 原始文件写入 MinIO，并创建数据库记录。
4. Celery 异步执行解析、切块、OCR、向量化和索引同步。
5. 文档状态按阶段回写为 `queued`、`parsing`、`chunking`、`indexing`、`ready`、`partial_failed`、`failed`。

### 问答链路

1. 用户在前端提交问题。
2. 后端执行限流、鉴权、上下文整理、安全检查和缓存预检。
3. Runtime V2 调用 `intent_router -> query_rewriter -> retriever -> 专项 agent / critic`。
4. 通过 SSE 返回事件流和最终答案。
5. 会话、引用、反馈、审计和运行指标被持久化。

### 管理治理链路

1. 管理员查看系统状态、检索指标、运行时任务和审计事件。
2. 可触发评估、重建索引、训练导出、训练编排等后台操作。
3. 结果进入 `reports/`、Redis 和数据库，供再次查询和验收。

## 4. Runtime V2

当前运行时已经以 Runtime V2 为主链路，具备：

- SSE 标准事件输出
- Trace、Replay、Checkpoint、Resume
- 运行时任务存储
- 工具调用决策记录
- 基础性能与拒绝率指标

这意味着系统已经不只是“一个普通聊天接口”，而是具备可观测和可追踪的运行内核。

## 5. 存储原则

- PostgreSQL 是唯一业务事实源
- ES / Milvus / Neo4j 均视为可重建的派生索引
- Redis 负责高频临时态，不承载最终事实
- MinIO 保存原始文档，不替代数据库元数据

## 6. 安全模型

- JWT 认证
- RBAC 管理权限控制
- 多租户隔离
- 上传文件扫描
- 输入 / 输出 Guard
- PII 脱敏与审计
- 管理端安全事件检索与汇总

## 7. 当前架构结论

当前仓库已经完成“企业文档平台底座 + Agent Runtime 主链路”的阶段目标。接下来的重点不是再换一套架构，而是在现有架构上继续增强：

- 中文文档理解质量
- 检索召回与引用质量
- 多轮追问体验
- 任务型文档 Agent 能力

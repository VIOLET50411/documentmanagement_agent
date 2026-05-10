# DocMind Agent Architecture

## 概述

DocMind Agent 是一个面向企业文档场景的问答与检索平台。当前架构采用“可运行内核 + 可降级 AI 能力”的策略：

- 基础链路必须稳定可运行：认证、上传、检索、SSE、审计都要先成立。
- AI 能力允许后续接入真实模型，但当前阶段始终保留可验证的 fallback。
- 多租户与安全策略默认按企业内部交付基线设计，不依赖单机演示逻辑。

## 五层架构

1. 前端层  
   基于 Vue3 + Vite，包含聊天页、文档管理、管理后台与运行态状态展示。

2. API 与编排层  
   基于 FastAPI，负责认证、RBAC、SSE、上传接口、管理接口和 Agent Runtime 编排。

3. 检索层  
   Elasticsearch 负责关键词检索，Milvus 负责向量检索，Neo4j 负责关系检索，通过统一检索入口做融合。

4. 数据处理层  
   Celery 异步处理文档解析、切块、向量化、索引同步和状态回写。

5. 存储与观测层  
   PostgreSQL 作为事实源，Redis 提供缓存和运行态队列，MinIO 存原始文件，日志和指标承担观测职责。

## 运行时主链路

### 查询链路

1. 用户在 Chat 页面提问。
2. 后端校验 JWT，注入租户与权限上下文。
3. 执行输入安全检查、PII 脱敏、语义缓存预检。
4. Agent Runtime 执行：意图识别 -> 查询改写 -> 检索/专业 Agent -> 生成/审查。
5. 通过 SSE 返回状态事件与最终回答，支持 replay 和 resume。
6. 回写会话消息、引用、反馈与安全审计。

### 入库链路

1. 用户上传文档。
2. 原始文件落到 MinIO，并创建后台任务。
3. Celery 依次执行解析 -> 切块 -> 向量化 -> ES/Milvus/Neo4j 建索引。
4. 进度和错误写入 Redis 与 PostgreSQL。
5. 文档状态进入 `ready`、`partial_failed` 或 `failed`。

## 存储设计

- PostgreSQL  
  保存用户、租户、权限、文档元数据、chunk 元数据、会话、反馈与审计记录，是唯一事实源。

- Redis  
  保存限流、语义缓存、任务进度、SSE replay 数据和运行态指标。

- MinIO  
  保存原始文档及其版本。

- Elasticsearch  
  保存全文索引与关键词召回数据。

- Milvus  
  保存向量索引。

- Neo4j  
  保存实体关系与关系查询索引。

设计原则：所有检索结果都必须能够追溯回 PostgreSQL 中的文档事实记录；ES、Milvus、Neo4j 都视为可重建的派生存储。

## 安全模型

1. JWT + RBAC 提供应用层权限控制。
2. PostgreSQL RLS 提供租户级隔离。
3. 上传、登录、验证码等入口做限流与审计。
4. 输入与输出都经过安全 Guard。
5. 支持 PII 脱敏与恢复映射。
6. 可按策略启用水印与 DLP 取证能力。
7. Guardrails / ClamAV sidecar 可按需要以 fail-closed 方式启用。

## 当前实现状态

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 基础设施 | 已完成 | FastAPI / Vue3 / Docker Compose / CI / 健康检查可运行 |
| 认证与多租户 | 已完成 | JWT、RLS、RBAC、邀请注册链路可用 |
| 文档入库 | 部分完成 | 主链路可运行，OCR 和高保真版面能力仍待增强 |
| 检索 | 部分完成 | ES + Milvus + Neo4j 已接入，仍需持续校准召回质量 |
| Agent Runtime | 已完成 | Runtime V2、SSE 事件协议、Checkpoint/Resume 已落地 |
| 安全基线 | 已完成 | 达到企业内部系统可交付基线 |
| 评估 | 部分完成 | 具备 sidecar 与本地 fallback 评估框架，质量门禁仍待强化 |

## 当前阶段的重点

1. 提升真实文档场景下的检索命中率与回答质量，而不是只证明链路存活。
2. 做好多轮追问、指代消解、版本歧义澄清等文档 Agent 能力。
3. 保持中文文案、提示词、规则词统一为 UTF-8，避免编码污染再次扩散。
4. 对 LangGraph Runtime、Checkpoint、Resume、安全审计等运行时治理持续补强。

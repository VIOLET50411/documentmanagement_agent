# DocMind Agent Architecture

## 概述

DocMind Agent 是一个企业文档问答与检索平台，当前采用“可运行内核 + 可降级 AI 能力”策略：

- 基础链路（鉴权、上传、检索、SSE、审计）必须稳定可运行
- AI 能力允许真实模型接入，但始终保留可观测的 fallback
- 多租户与安全策略默认收敛到企业可交付基线

## 五层架构

1. 前端层  
   Vue3 + Vite，包含聊天、文档管理、管理后台。
2. API 与编排层  
   FastAPI 提供认证、RBAC、SSE、上传、管理接口与 Agent Runtime。
3. 检索层  
   Elasticsearch（关键词）+ Milvus（向量）+ Neo4j（关系）并发检索，统一融合。
4. 数据处理层  
   Celery 异步处理文档解析、切块、向量化、索引同步和状态回写。
5. 存储与观测层  
   PostgreSQL（事实源）+ Redis（缓存/队列/指标）+ MinIO（原文件）+ Prometheus/结构化日志。

## 运行时主链路

### 查询链路

1. 用户在 Chat 提问。
2. 后端校验 JWT、注入租户与权限上下文。
3. 输入安全检查、PII 脱敏、语义缓存预检。
4. Agent Runtime 执行：意图路由 -> 检索编排 -> 生成/审查 -> 事件流输出。
5. SSE 返回状态事件与内容事件，支持 replay/续传。
6. 回写会话消息、引用、反馈与审计。

### 入库链路

1. 用户上传文件到文档接口。
2. 文件落 MinIO，创建后台任务。
3. Celery 执行：解析 -> 切块 -> 向量化 -> ES/Milvus/Neo4j 索引。
4. 进度与错误写入 Redis + PostgreSQL。
5. 文档状态进入 `ready / partial_failed / failed`。

## 存储设计（冷热分层）

- PostgreSQL：用户、租户、权限、文档元数据、chunk 元数据、会话、反馈、审计（唯一事实源）。
- Redis：限流、语义缓存、任务进度、SSE replay、运行时指标。
- MinIO：原始文件与版本。
- Elasticsearch：全文索引与关键词召回。
- Milvus：向量召回。
- Neo4j：实体关系召回。

设计原则：所有检索结果都必须可回查 PostgreSQL 主记录，ES/Milvus/Neo4j 均视为可重建派生存储。

## 安全模型

1. JWT + RBAC（应用层权限）。
2. PostgreSQL RLS（租户隔离）。
3. 上传/登录/验证码限流与审计。
4. Input Guard / Output Guard / Sanitizer。
5. PII 脱敏与可恢复映射。
6. 水印与 DLP 取证（按策略启用）。
7. Guardrails/ClamAV sidecar（可 fail-closed）。

## 当前实现状态（2026-04）

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 基础设施 | 已完成 | FastAPI/Vue3/Compose/CI/健康检查可运行 |
| 鉴权与多租户 | 已完成 | JWT、RLS、RBAC、邀请注册链路可用 |
| ETL | 部分完成 | 主链路可运行，OCR/版面高保真仍待增强 |
| 检索 | 部分完成 | ES+Milvus+Neo4j 已接入，仍需持续校准 |
| Agent Runtime | 已完成（v2） | 统一任务、SSE 事件协议、工具决策审计 |
| 安全基线 | 已完成 | 企业内网可上线基线，非金融终态 |
| 评估 | 部分完成 | Ragas sidecar 已接，真实评估稳定性待持续验证 |

## 后续重点

1. P0：真实 LLM/Embedding/Reranker 端到端稳定性验证与压测达标。
2. P1：工程质量收口（异常收窄、测试补齐、文档解析增强）。
3. P3/P4：安全联动与 LangGraph 状态机升级。

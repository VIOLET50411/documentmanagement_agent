# DocMind 系统设计说明

## 1. 设计目标

系统设计的核心不是追求概念堆叠，而是保证以下几点：

- 文档主链路稳定可运行
- 检索与问答可扩展
- 安全与租户隔离不被后续功能破坏
- Runtime、评估、训练等治理能力能逐步增强

## 2. 模块划分

### backend

- `app/api`：HTTP 接口
- `app/agent`：Runtime、节点、专项 agent
- `app/ingestion`：解析、OCR、切块、嵌入
- `app/retrieval`：ES / Milvus / Neo4j / 混合检索
- `app/services`：业务服务、评估、训练、系统治理
- `app/security`：输入输出守卫、PII、扫描

### frontend

- `views`：页面
- `components`：复用组件
- `stores`：状态管理
- `services`：HTTP / SSE / 业务请求封装

### infra

- Guardrails sidecar
- Ragas sidecar
- Docker 辅助运行环境

## 3. 关键设计约束

### 业务事实与索引分离

- PostgreSQL 负责事实数据
- 检索索引全部可重建

### 同步请求与异步任务分离

- API 负责发起和查询
- Celery 负责重任务执行

### 主链路与 AI 占位分离

- AI 可替换
- 主链路不可因此中断

### 用户可见文本统一编码

- 中文文本、prompt、规则词、文档说明统一 UTF-8
- 乱码视为缺陷，不作为可接受状态保留

## 4. 当前设计结论

这套系统设计已经足以支撑“文档平台 + 文档 Agent”的继续迭代。后续不需要推翻式重来，更适合在现有边界内做质量增强和体验收敛。

# 企业领域模型与训练编排说明

## 1. 当前范围

本仓库已经包含企业语料导出、训练任务编排、模型注册和激活入口，但这不等于完整生产级训练平台已经完成。

## 2. 当前已具备的能力

### 运行时模型路由

支持通过环境变量配置企业领域模型路由，例如：

- `LLM_ENTERPRISE_ENABLED`
- `LLM_ENTERPRISE_API_BASE_URL`
- `LLM_ENTERPRISE_MODEL_NAME`
- `LLM_ENTERPRISE_KEYWORDS`
- `LLM_ENTERPRISE_FORCE_TENANTS`
- `LLM_ENTERPRISE_CANARY_PERCENT`

### 企业语料导出

管理端已提供：

- `GET /api/v1/admin/llm/domain-config`
- `POST /api/v1/admin/llm/domain-corpus/export`
- `GET /api/v1/admin/llm/public-corpus/latest`
- `POST /api/v1/admin/llm/public-corpus/export-async`

### 训练与模型注册

当前已提供：

- `POST /api/v1/admin/llm/training/run-async`
- `GET /api/v1/admin/llm/training/jobs`
- `GET /api/v1/admin/llm/training/jobs/{job_id}`
- `GET /api/v1/admin/llm/models`
- `POST /api/v1/admin/llm/models/{model_id}/activate`

## 3. 当前边界

已经有：

- 导出入口
- 训练任务编排
- 模型注册
- 租户维度激活

还没有彻底完成：

- 真实大规模 GPU 训练平台
- 自动生成和发布生产推理服务
- 完整灰度与回滚自动化
- 与质量门禁完全联动的发布闭环

## 4. 推荐使用方式

当前更适合把这部分能力视为“为后续企业文档专项模型做准备的工程入口”，而不是把它描述成已经成熟的训练平台。

# 企业管理文档模型适配说明

## 目标

DocMind 当前已经具备两类企业领域模型适配能力：

1. 运行时领域模型路由
2. 企业管理文档语料导出与训练编排

这两项能力用于把“后续要做微调”落成可执行工程，而不是停留在口头方案。

## 一、运行时领域模型路由

可用环境变量：

```env
LLM_ENTERPRISE_ENABLED=true
LLM_ENTERPRISE_API_BASE_URL=http://ollama:11434/v1
LLM_ENTERPRISE_MODEL_NAME=qwen2.5:7b
LLM_ENTERPRISE_API_KEY=
LLM_ENTERPRISE_KEYWORDS=制度,审批,流程,合规,预算,采购,合同,报销,风控,审计,人事,绩效,会议纪要,管理办法
LLM_ENTERPRISE_FORCE_TENANTS=default
LLM_ENTERPRISE_CANARY_PERCENT=20
LLM_ENTERPRISE_CANARY_SEED=docmind-enterprise-llm
```

触发条件：

- 问题命中企业管理关键词
- 当前租户在 `LLM_ENTERPRISE_FORCE_TENANTS` 中
- 或命中企业模型灰度桶

命中后，`LLMService` 会优先使用企业领域模型，而不是默认通用模型。

## 二、企业语料导出

管理端接口：

- `GET /api/v1/admin/llm/domain-config`
- `POST /api/v1/admin/llm/domain-corpus/export`
- `GET /api/v1/admin/llm/public-corpus/latest`
- `POST /api/v1/admin/llm/public-corpus/export-async`

导出参数：

- `doc_limit`：扫描的文档上限
- `chunk_limit`：导出的片段上限
- `keywords`：按逗号传入的领域关键词
- `max_access_level`：只保留不高于该权限级别的文档
- `deduplicate`：是否按内容指纹去重
- `train_ratio`：SFT 训练集切分比例

导出结果位于：

```text
reports/domain_tuning/<tenant_id>/<timestamp-or-dataset_timestamp>/
```

会生成这些文件：

- `enterprise_cpt.jsonl`
- `enterprise_sft.jsonl`
- `enterprise_sft_train.jsonl`
- `enterprise_sft_val.jsonl`
- `excluded_records.jsonl`
- `manifest.json`

含义：

- `enterprise_cpt.jsonl`：适合继续预训练或领域自适应
- `enterprise_sft.jsonl`：全部合格监督样本
- `enterprise_sft_train.jsonl` / `enterprise_sft_val.jsonl`：可直接进入后续 LoRA / SFT
- `excluded_records.jsonl`：记录权限过滤、敏感过滤、去重过滤被剔除的片段
- `manifest.json`：记录导出统计、关键词命中、文档分布、训练可用性

## 三、训练编排与模型注册

当前版本新增了训练闭环的第一版：

- `POST /api/v1/admin/llm/training/run-async`
- `GET /api/v1/admin/llm/training/jobs`
- `GET /api/v1/admin/llm/training/jobs/{job_id}`
- `GET /api/v1/admin/llm/models`
- `POST /api/v1/admin/llm/models/{model_id}/activate`

当前实现内容：

- 按租户创建训练任务
- 读取最近一次导出的 `manifest.json`
- 校验训练样本量是否满足最小要求
- 生成训练产物目录与模型卡
- 自动注册模型到租户模型注册表
- 可在租户维度激活模型
- 激活状态写入 Redis，运行时可读取

当前训练产物目录：

```text
reports/model_training/<tenant_id>/<job_id>/
```

当前属于“训练编排 + 注册 + 激活”阶段，不等于已经接入真实 GPU LoRA/SFT 执行器。

## 四、推荐微调路线

### 阶段 1：先做路由和语料

- 使用当前系统中的制度、流程、审批、合规文档导出语料
- 清洗敏感信息、过期文档、重复文档
- 先通过领域模型路由验证真实收益

### 阶段 2：低成本微调

- 优先做 LoRA / QLoRA
- 任务以问答、制度摘要、审批链路抽取、风险提示为主
- 不建议一开始就做全量继续预训练

### 阶段 3：评估和灰度

- 用平台现有评估集扩充企业管理问题集
- 对比通用模型与企业模型的 faithfulness、relevancy、引用命中率
- 通过租户灰度或关键词灰度逐步切流

## 五、语料治理要求

- 只导出已生效、已审批、可内部训练使用的文档
- 训练前先做 PII 脱敏和权限审计
- 法务、财务、人事类高敏内容要单独审核
- 不要把原始全量文档无筛选投入训练
- 当前导出器已经默认过滤高敏内容、过高访问级别片段与重复片段

## 六、当前边界

当前版本已经支持：

- 领域模型运行时切换
- 企业语料自动导出
- 训练任务编排
- 模型注册与租户激活

当前版本还没有内置：

- 真实 GPU 训练调度
- 自动产出 LoRA 权重
- 自动部署新的推理服务
- 基于真实训练产物的全自动灰度上线

这些属于下一阶段，需要结合 GPU 环境、模型仓库和评估门禁继续落地。

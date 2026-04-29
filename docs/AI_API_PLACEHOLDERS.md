# AI API Integration Status

本文档用于明确 DocMind 当前各类 AI / 检索增强能力的接入边界，避免“部分真实接入、部分 fallback、文档却写不清”的混合状态。

## 当前已真实接入（可配置开启）

### LLM

- `backend/app/services/llm_service.py`
  - 已支持 `Ollama` 与 OpenAI-compatible 接口
  - 已具备健康检查、超时、熔断、流式输出能力

### Embedding

- `backend/app/ingestion/embedder.py`
  - 已支持远程 embedding 调用
  - 已支持自动检测真实向量维度并持久化到 Redis 键 `embedding:detected_dim`
  - 远程失败时会回退到本地 deterministic fallback，并按真实维度自动补零对齐

### Reranker（过渡方案）

- `backend/app/retrieval/reranker.py`
  - 当前支持远程 reranker 接口、LLM 代理重排与本地规则降级
  - 仍建议后续收口到独立 reranker 服务，例如 `BAAI/bge-reranker-v2-m3`

### Runtime / Checkpoint

- `backend/app/agent/runtime/*`
  - Runtime V2 为当前唯一生产链路
  - 已支持运行时任务状态、工具治理、SSE 事件协议、Redis replay
- `backend/app/agent/runtime/langgraph_runner.py`
  - 已支持 LangGraph 图执行
  - 已支持 PostgreSQL checkpoint 持久化与恢复续跑

## 当前仍以 fallback / placeholder 为主

### 文档解析与 OCR

- `backend/app/ingestion/parsers/pdf_parser.py`
- `backend/app/ingestion/parsers/ocr_parser.py`

现状：
- 已具备 `unstructured` / `pypdf` / `PaddleOCR` 的真实接入路径
- 但在依赖缺失或运行失败时仍会优雅降级到 `ocr_notice` / fallback 文本
- 距离“生产级高保真解析”仍有差距，后续还可继续加强版面分析、表格结构和扫描件精度

### 安全增强

- `backend/app/security/pii_masker.py`
- `backend/app/security/input_guard.py`
- `backend/app/security/output_guard.py`
- `infra/guardrails_sidecar/app/main.py`

现状：
- 已具备 Presidio 可选接入与本地规则兜底
- 已具备 Guardrails sidecar 健康检查、输入/输出审查、fail-open / fail-closed 策略
- 但当前 sidecar 规则仍偏轻量，距离更严格的金融级策略联动仍有差距

### 评估

- `backend/app/evaluation/ragas_runner.py`
- `backend/app/services/evaluation_service.py`
- `infra/ragas_sidecar/app/main.py`

现状：
- 已支持真实 Ragas sidecar 调用
- sidecar 可在真实评估不可用时回退为 heuristic 模式
- CI 门禁、real-mode 强约束、评估报告输出已具备框架与服务端实现
- 若要达到最终“强门禁终态”，仍需稳定真实评估环境与 Golden Dataset 长期维护

## 关键配置示例

```env
LLM_PROVIDER=ollama
LLM_API_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen2.5:7b

EMBEDDING_PROVIDER=ollama
EMBEDDING_API_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL_NAME=nomic-embed-text

RERANKER_PROVIDER=llm
RERANKER_API_BASE_URL=
HYBRID_VECTOR_ENABLED=true
VECTOR_LOCAL_FALLBACK_ENABLED=true

PII_PRESIDIO_ENABLED=true
GUARDRAILS_ENABLED=true
GUARDRAILS_SIDECAR_URL=http://guardrails-sidecar:8090
GUARDRAILS_FAIL_CLOSED=false

RAGAS_API_BASE_URL=http://ragas-sidecar:8091
RAGAS_REQUIRE_REAL_MODE=true
CI_GATE_REQUIRE_REAL_RAGAS=true
```

## 当前工程判断

- LLM / Embedding / Runtime / Checkpoint 已不再是“纯占位”
- 文档解析、OCR、安全 sidecar、Ragas 评估属于“真实接入 + 降级共存”的阶段
- 因此后续工作重点不应再写成“完全未接入”，而应聚焦：
  1. 提升真实路径覆盖率
  2. 缩小 fallback 触发面
  3. 用测试、压测、CI 门禁证明真实路径稳定可用

## 下一步建议

1. 继续加强 P2：文档解析与 OCR 的真实依赖安装、扫描件质量、表格结构抽取。
2. 继续加强 P3：Guardrails / Presidio / Ragas 的真实环境部署与 fail-closed 策略验证。
3. 继续加强 P4：LangGraph native checkpoint 的端到端恢复验证与版本兼容升级。

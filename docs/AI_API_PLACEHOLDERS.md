# AI API Integration Status

本文档用于标记 DocMind 中“已接真实模型 / 仍为 fallback / 待接入”的边界，避免真假混合导致交付不可验证。

## 当前真实接入（可开关）

### LLM

- `backend/app/services/llm_service.py`
  - 已支持 Ollama / OpenAI-compatible 接口
  - 含健康检查、超时、熔断、流式输出

### Embedding

- `backend/app/ingestion/embedder.py`
  - 已支持远程 embedding 调用
  - 已支持检测向量维度并持久化到 Redis（`embedding:detected_dim`）
  - 远程失败时本地 fallback 自动按真实维度补齐

### Reranker（过渡方案）

- `backend/app/retrieval/reranker.py`
  - 当前支持 LLM 代理排序 + 本地降级
  - 下一阶段替换为独立 reranker 服务（如 BGE-reranker API）

## 当前仍是 fallback / placeholder

### 文档解析与 OCR

- `backend/app/ingestion/parsers/pdf_parser.py`
- `backend/app/ingestion/parsers/ocr_parser.py`

现状：可运行但不是生产级高保真解析，仍需引入 unstructured/docling + PaddleOCR。

### 安全模型增强

- `backend/app/security/pii_masker.py`
- `backend/app/security/input_guard.py`
- `backend/app/security/output_guard.py`

现状：规则可用，sidecar 已预留，模型化能力待增强。

### 评估

- `backend/app/evaluation/ragas_runner.py`
- `infra/ragas_sidecar/app/main.py`

现状：支持真实 Ragas 调用与回退；真实评估稳定性、数据集和 CI 强门禁仍在持续收口。

## 关键配置（示例）

```env
LLM_PROVIDER=ollama
LLM_API_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen2.5:7b

EMBEDDING_PROVIDER=ollama
EMBEDDING_API_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL_NAME=nomic-embed-text

RERANKER_PROVIDER=llm
HYBRID_VECTOR_ENABLED=true
VECTOR_LOCAL_FALLBACK_ENABLED=true

RAGAS_API_BASE_URL=http://localhost:8091
RAGAS_REQUIRE_REAL_MODE=true
CI_GATE_REQUIRE_REAL_RAGAS=true
```

## 下一步（与路线图对齐）

1. 完成 P0：启动健康检查、端到端真实调用冒烟、维度一致性验证。
2. 完成 P2：真实 PDF/OCR 解析与 reranker 独立服务化。
3. 完成 P3：PII/Guardrails 模型化 + Ragas 强门禁稳定运行。

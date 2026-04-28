from __future__ import annotations

import asyncio
import math
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="DocMind Ragas Sidecar", version="0.2.0")


@app.on_event("startup")
async def startup_event() -> None:
    try:
        import nltk

        nltk.download("punkt", quiet=True)
    except Exception:
        pass


class EvaluateRequest(BaseModel):
    dataset: list[dict[str, Any]]


def _overlap(left: str, right: str) -> float:
    left_tokens = {token for token in left.split() if token}
    right_tokens = {token for token in right.split() if token}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _heuristic(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    if not dataset:
        return {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
            "sample_count": 0,
            "real_mode": False,
            "engine": "heuristic",
        }
    f = []
    r = []
    p = []
    c = []
    for row in dataset:
        answer = (row.get("answer") or row.get("response") or "").strip()
        contexts = row.get("contexts") or row.get("retrieved_contexts") or []
        context_text = " ".join(contexts).strip()
        question = (row.get("question") or row.get("user_input") or "").strip()
        f.append(_overlap(answer, context_text))
        r.append(_overlap(answer, question + " " + context_text))
        p.append(_overlap(context_text, answer))
        c.append(_overlap(answer, context_text))
    return {
        "faithfulness": round(sum(f) / len(f), 4),
        "answer_relevancy": round(sum(r) / len(r), 4),
        "context_precision": round(sum(p) / len(p), 4),
        "context_recall": round(sum(c) / len(c), 4),
        "sample_count": len(dataset),
        "real_mode": False,
        "engine": "heuristic",
    }


def _use_ollama_backend(base_url: str) -> bool:
    lowered = (base_url or "").lower()
    return "ollama" in lowered or lowered.endswith(":11434/v1") or lowered.endswith(":11434")


def _normalize_dataset(dataset: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        "user_input": [str(item.get("user_input") or item.get("question") or "") for item in dataset],
        "response": [str(item.get("response") or item.get("answer") or "") for item in dataset],
        "retrieved_contexts": [item.get("retrieved_contexts") or item.get("contexts") or [] for item in dataset],
        "reference": [str(item.get("reference") or item.get("ground_truth") or "") for item in dataset],
    }


def _safe_metric(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(result) or math.isinf(result):
        return 0.0
    return result


async def _ragas_eval(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    if not dataset:
        return {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
            "sample_count": 0,
            "real_mode": True,
            "engine": "ragas",
        }

    ds = Dataset.from_dict(_normalize_dataset(dataset))

    llm_base = os.getenv("RAGAS_LLM_BASE_URL", "http://ollama:11434")
    llm_model = os.getenv("RAGAS_LLM_MODEL", "qwen2.5:1.5b")
    embed_base = os.getenv("RAGAS_EMBEDDING_BASE_URL", "http://ollama:11434")
    embed_model = os.getenv("RAGAS_EMBEDDING_MODEL", "nomic-embed-text")
    api_key = os.getenv("RAGAS_API_KEY", "dummy")

    if _use_ollama_backend(llm_base):
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=llm_model, base_url=llm_base, api_key=api_key, temperature=0.0)
        if _use_ollama_backend(embed_base):
            from langchain_ollama import OllamaEmbeddings

            emb = OllamaEmbeddings(model=embed_model, base_url=embed_base.replace("/v1", ""))
        else:
            from langchain_openai import OpenAIEmbeddings

            emb = OpenAIEmbeddings(model=embed_model, base_url=embed_base, api_key=api_key)
        engine = "ragas_ollama"
    else:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        llm = ChatOpenAI(model=llm_model, base_url=llm_base, api_key=api_key, temperature=0.0)
        emb = OpenAIEmbeddings(model=embed_model, base_url=embed_base, api_key=api_key)
        engine = "ragas_openai_compat"

    def _run_eval():
        return evaluate(
            ds,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            llm=LangchainLLMWrapper(llm),
            embeddings=LangchainEmbeddingsWrapper(emb),
        )

    result = await asyncio.to_thread(_run_eval)
    data = result.to_pandas().mean(numeric_only=True).to_dict()
    return {
        "faithfulness": _safe_metric(data.get("faithfulness", 0.0)),
        "answer_relevancy": _safe_metric(data.get("answer_relevancy", 0.0)),
        "context_precision": _safe_metric(data.get("context_precision", 0.0)),
        "context_recall": _safe_metric(data.get("context_recall", 0.0)),
        "sample_count": len(dataset),
        "real_mode": True,
        "engine": engine,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    llm_base = os.getenv("RAGAS_LLM_BASE_URL", "http://ollama:11434")
    embed_base = os.getenv("RAGAS_EMBEDDING_BASE_URL", "http://ollama:11434")
    return {
        "ok": True,
        "status": "online",
        "llm_backend": "ollama" if _use_ollama_backend(llm_base) else "openai_compat",
        "embedding_backend": "ollama" if _use_ollama_backend(embed_base) else "openai_compat",
    }


@app.post("/evaluate")
async def evaluate_endpoint(payload: EvaluateRequest) -> dict[str, Any]:
    prefer_real = os.getenv("RAGAS_PREFER_REAL", "true").lower() == "true"
    timeout_seconds = float(os.getenv("RAGAS_TIMEOUT_SECONDS", "180"))
    if prefer_real:
        try:
            return await asyncio.wait_for(_ragas_eval(payload.dataset), timeout=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            fallback = _heuristic(payload.dataset)
            fallback["error"] = f"{type(exc).__name__}: {exc}"
            return fallback
    return _heuristic(payload.dataset)

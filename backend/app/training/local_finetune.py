"""Local LoRA/SFT training helpers used by the script executor."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LocalTrainingContext:
    request: dict[str, Any]
    manifest: dict[str, Any]
    artifact_dir: Path
    train_path: Path
    val_path: Path
    base_model: str
    hf_base_model: str
    target_model_name: str
    serving_base_url: str
    serving_model_name: str


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_training_context(request_json_path: str | Path) -> LocalTrainingContext:
    request_path = Path(request_json_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    artifact_dir = Path(str(request.get("artifact_dir") or "")).resolve()
    if not artifact_dir:
        raise ValueError("\u8bad\u7ec3\u8bf7\u6c42\u7f3a\u5c11 artifact_dir")
    manifest_path = Path(str(request.get("manifest_path") or "")).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"\u8bad\u7ec3 manifest \u4e0d\u5b58\u5728: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = manifest.get("paths") or {}
    train_path = Path(str(paths.get("sft_train") or "")).resolve()
    val_path = Path(str(paths.get("sft_val") or "")).resolve()
    if not train_path.exists():
        raise FileNotFoundError(f"\u8bad\u7ec3\u96c6\u4e0d\u5b58\u5728: {train_path}")
    if not val_path.exists():
        raise FileNotFoundError(f"\u9a8c\u8bc1\u96c6\u4e0d\u5b58\u5728: {val_path}")

    base_model = str(request.get("base_model") or "").strip()
    hf_base_model = resolve_hf_base_model(base_model)
    target_model_name = str(request.get("target_model_name") or request.get("job_id") or "docmind-lora").strip()
    serving_base_url = (
        os.getenv("DOCMIND_TRAINING_SERVING_BASE_URL")
        or os.getenv("LLM_ENTERPRISE_API_BASE_URL")
        or os.getenv("LLM_API_BASE_URL")
        or "http://ollama:11434/v1"
    ).strip()
    serving_model_name = (
        os.getenv("DOCMIND_TRAINING_SERVING_MODEL_NAME")
        or os.getenv("LLM_ENTERPRISE_MODEL_NAME")
        or os.getenv("LLM_MODEL_NAME")
        or base_model
        or target_model_name
    ).strip()

    artifact_dir.mkdir(parents=True, exist_ok=True)
    return LocalTrainingContext(
        request=request,
        manifest=manifest,
        artifact_dir=artifact_dir,
        train_path=train_path,
        val_path=val_path,
        base_model=base_model,
        hf_base_model=hf_base_model,
        target_model_name=target_model_name,
        serving_base_url=serving_base_url,
        serving_model_name=serving_model_name,
    )


def resolve_hf_base_model(base_model: str) -> str:
    override = os.getenv("DOCMIND_TRAINING_HF_BASE_MODEL", "").strip()
    if override:
        return override
    if _env_flag("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED"):
        return os.getenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "sshleifer/tiny-gpt2").strip()
    normalized = base_model.strip().lower()
    mapping = {
        "qwen2.5:1.5b": "Qwen/Qwen2.5-1.5B-Instruct",
        "qwen2.5:3b": "Qwen/Qwen2.5-3B-Instruct",
        "qwen2.5:7b": "Qwen/Qwen2.5-7B-Instruct",
        "qwen2.5:14b": "Qwen/Qwen2.5-14B-Instruct",
        "llama3.1:8b": "meta-llama/Llama-3.1-8B-Instruct",
        "llama3.1:70b": "meta-llama/Llama-3.1-70B-Instruct",
        "tinyllama": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    }
    return mapping.get(normalized, base_model)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def build_supervised_text(messages: list[dict[str, Any]]) -> str:
    role_map = {"system": "\u7cfb\u7edf", "user": "\u7528\u6237", "assistant": "\u52a9\u624b"}
    lines: list[str] = []
    for item in messages:
        role = role_map.get(str(item.get("role") or "").strip().lower(), "\u6d88\u606f")
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"<{role}>\\n{content}\\n</{role}>")
    return "\\n\\n".join(lines)


def build_dataset_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        text = build_supervised_text(messages)
        if not text:
            continue
        rows.append(
            {
                "text": text,
                "doc_id": str(record.get("doc_id") or record.get("metadata", {}).get("doc_id") or ""),
                "tenant_id": str(record.get("tenant_id") or ""),
            }
        )
    return rows


def build_training_plan(context: LocalTrainingContext, train_rows: list[dict[str, Any]], val_rows: list[dict[str, Any]]) -> dict[str, Any]:
    dev_tiny_mode = _env_flag("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED")
    default_target_modules = "q_proj" if dev_tiny_mode else "q_proj,v_proj,k_proj,o_proj,gate_proj,up_proj,down_proj"
    default_max_steps = "1" if dev_tiny_mode else "10"
    default_grad_accum = "1" if dev_tiny_mode else "4"
    default_lora_r = "2" if dev_tiny_mode else "8"
    default_lora_alpha = "4" if dev_tiny_mode else "16"
    default_max_train_samples = "4" if dev_tiny_mode else "0"
    default_max_val_samples = "1" if dev_tiny_mode else "0"
    return {
        "job_id": context.request.get("job_id"),
        "tenant_id": context.request.get("tenant_id"),
        "dataset_name": context.request.get("dataset_name"),
        "base_model": context.base_model,
        "hf_base_model": context.hf_base_model,
        "target_model_name": context.target_model_name,
        "artifact_dir": str(context.artifact_dir),
        "train_records": len(train_rows),
        "val_records": len(val_rows),
        "lora": {
            "r": int(os.getenv("DOCMIND_TRAINING_LORA_R", default_lora_r)),
            "alpha": int(os.getenv("DOCMIND_TRAINING_LORA_ALPHA", default_lora_alpha)),
            "dropout": float(os.getenv("DOCMIND_TRAINING_LORA_DROPOUT", "0.05")),
            "target_modules": [
                module.strip()
                for module in os.getenv("DOCMIND_TRAINING_TARGET_MODULES", default_target_modules).split(",")
                if module.strip()
            ],
        },
        "trainer": {
            "epochs": float(os.getenv("DOCMIND_TRAINING_EPOCHS", "1")),
            "learning_rate": float(os.getenv("DOCMIND_TRAINING_LEARNING_RATE", "0.0002")),
            "max_steps": int(os.getenv("DOCMIND_TRAINING_MAX_STEPS", default_max_steps)),
            "micro_batch_size": int(os.getenv("DOCMIND_TRAINING_BATCH_SIZE", "1")),
            "gradient_accumulation_steps": int(os.getenv("DOCMIND_TRAINING_GRAD_ACCUM", default_grad_accum)),
            "max_train_samples": int(os.getenv("DOCMIND_TRAINING_MAX_TRAIN_SAMPLES", default_max_train_samples)),
            "max_val_samples": int(os.getenv("DOCMIND_TRAINING_MAX_VAL_SAMPLES", default_max_val_samples)),
        },
        "publish": {
            "publish_enabled": os.getenv("DOCMIND_TRAINING_PUBLISH_ENABLED", "false").lower() == "true",
            "publish_ready": False,
            "serving_base_url": context.serving_base_url,
            "serving_model_name": context.serving_model_name,
        },
    }


def write_training_artifacts(
    context: LocalTrainingContext,
    *,
    plan: dict[str, Any],
    executed: bool,
    adapter_dir: str | None,
    notes: str,
    publish_ready: bool,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan_path = context.artifact_dir / "training_plan.json"
    manifest_path = context.artifact_dir / "adapter_manifest.json"
    modelfile_path = context.artifact_dir / "Modelfile"
    model_card_path = context.artifact_dir / "model_card.md"
    result_path = context.artifact_dir / "training_result.json"

    plan["publish"]["publish_ready"] = bool(publish_ready)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    adapter_manifest = {
        "job_id": context.request.get("job_id"),
        "tenant_id": context.request.get("tenant_id"),
        "dataset_name": context.request.get("dataset_name"),
        "base_model": context.base_model,
        "hf_base_model": context.hf_base_model,
        "target_model_name": context.target_model_name,
        "artifact_dir": str(context.artifact_dir),
        "adapter_dir": adapter_dir,
        "executed": executed,
        "publish_ready": bool(publish_ready),
        "notes": notes,
    }
    manifest_path.write_text(json.dumps(adapter_manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    modelfile_lines = [f"FROM {context.base_model}"]
    if adapter_dir:
        adapter_name = Path(adapter_dir).name
        modelfile_lines.append(f"ADAPTER ./{adapter_name}")
    modelfile_lines.append(f'PARAMETER num_ctx {os.getenv("DOCMIND_TRAINING_OLLAMA_NUM_CTX", "4096")}')
    modelfile_path.write_text("\n".join(modelfile_lines) + "\n", encoding="utf-8", newline="\n")

    model_card_lines = [
        f"# {context.target_model_name}",
        "",
        f"- tenant_id: {context.request.get('tenant_id')}",
        f"- dataset_name: {context.request.get('dataset_name')}",
        f"- base_model: {context.base_model}",
        f"- hf_base_model: {context.hf_base_model}",
        f"- executed: {executed}",
        f"- publish_ready: {publish_ready}",
        "",
        "## Notes",
        "",
        notes,
    ]
    model_card_path.write_text("\n".join(model_card_lines) + "\n", encoding="utf-8", newline="\n")

    executor_metadata = {
        "executor": "script",
        "mode": "executed" if executed else "plan_only",
        "publish_ready": bool(publish_ready),
        "plan_path": str(plan_path),
        "adapter_manifest_path": str(manifest_path),
        "modelfile_path": str(modelfile_path),
    }
    if extra_metadata:
        executor_metadata.update(extra_metadata)

    result = {
        "artifact_dir": str(context.artifact_dir),
        "serving_base_url": context.serving_base_url,
        "serving_model_name": context.serving_model_name,
        "executor_metadata": executor_metadata,
        "notes": notes,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return result

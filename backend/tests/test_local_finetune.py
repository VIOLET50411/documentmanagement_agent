from __future__ import annotations

import json
from pathlib import Path

from app.training.local_finetune import (
    build_dataset_rows,
    build_training_plan,
    load_training_context,
    read_jsonl,
    write_training_artifacts,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n", encoding="utf-8")


def test_load_training_context_and_plan(tmp_path: Path, monkeypatch):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    artifact_dir = tmp_path / "artifacts"
    train_path = export_dir / "enterprise_sft_train.jsonl"
    val_path = export_dir / "enterprise_sft_val.jsonl"
    manifest_path = export_dir / "manifest.json"

    _write_jsonl(
        train_path,
        [
            {
                "tenant_id": "default",
                "doc_id": "doc-1",
                "messages": [
                    {"role": "system", "content": "\u7cfb\u7edf\u63d0\u793a"},
                    {"role": "user", "content": "\u95ee\u9898\u4e00"},
                    {"role": "assistant", "content": "\u56de\u7b54\u4e00"},
                ],
            }
        ],
    )
    _write_jsonl(
        val_path,
        [
            {
                "tenant_id": "default",
                "doc_id": "doc-2",
                "messages": [
                    {"role": "user", "content": "\u95ee\u9898\u4e8c"},
                    {"role": "assistant", "content": "\u56de\u7b54\u4e8c"},
                ],
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "paths": {
                    "sft_train": str(train_path),
                    "sft_val": str(val_path),
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request_json_path = tmp_path / "training_request.json"
    request_json_path.write_text(
        json.dumps(
            {
                "job_id": "job-1",
                "tenant_id": "default",
                "dataset_name": "swu_public_docs",
                "base_model": "qwen2.5:7b",
                "manifest_path": str(manifest_path),
                "artifact_dir": str(artifact_dir),
                "target_model_name": "default-swu",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DOCMIND_TRAINING_SERVING_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("DOCMIND_TRAINING_SERVING_MODEL_NAME", "qwen2.5:7b")
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "false")
    monkeypatch.delenv("DOCMIND_TRAINING_HF_BASE_MODEL", raising=False)
    context = load_training_context(request_json_path)
    train_rows = build_dataset_rows(read_jsonl(context.train_path))
    val_rows = build_dataset_rows(read_jsonl(context.val_path))
    plan = build_training_plan(context, train_rows, val_rows)

    assert context.target_model_name == "default-swu"
    assert context.hf_base_model == "Qwen/Qwen2.5-7B-Instruct"
    assert train_rows[0]["text"].startswith("<\u7cfb\u7edf>")
    assert plan["train_records"] == 1
    assert plan["hf_base_model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert plan["publish"]["publish_ready"] is False


def test_load_training_context_prefers_dev_tiny_model(tmp_path: Path, monkeypatch):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    train_path = export_dir / "enterprise_sft_train.jsonl"
    val_path = export_dir / "enterprise_sft_val.jsonl"
    manifest_path = export_dir / "manifest.json"
    _write_jsonl(train_path, [])
    _write_jsonl(val_path, [])
    manifest_path.write_text(json.dumps({"paths": {"sft_train": str(train_path), "sft_val": str(val_path)}}), encoding="utf-8")
    request_json_path = tmp_path / "training_request.json"
    request_json_path.write_text(
        json.dumps(
            {
                "job_id": "job-dev",
                "tenant_id": "default",
                "dataset_name": "swu_public_docs",
                "base_model": "qwen2.5:7b",
                "manifest_path": str(manifest_path),
                "artifact_dir": str(tmp_path / "artifacts"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "true")
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "sshleifer/tiny-gpt2")
    context = load_training_context(request_json_path)
    assert context.hf_base_model == "sshleifer/tiny-gpt2"


def test_build_training_plan_uses_dev_tiny_defaults(tmp_path: Path, monkeypatch):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    train_path = export_dir / "enterprise_sft_train.jsonl"
    val_path = export_dir / "enterprise_sft_val.jsonl"
    manifest_path = export_dir / "manifest.json"
    _write_jsonl(train_path, [])
    _write_jsonl(val_path, [])
    manifest_path.write_text(json.dumps({"paths": {"sft_train": str(train_path), "sft_val": str(val_path)}}), encoding="utf-8")
    request_json_path = tmp_path / "training_request.json"
    request_json_path.write_text(
        json.dumps(
            {
                "job_id": "job-dev-plan",
                "tenant_id": "default",
                "dataset_name": "swu_public_docs",
                "base_model": "tinyllama",
                "manifest_path": str(manifest_path),
                "artifact_dir": str(tmp_path / "artifacts"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "true")
    context = load_training_context(request_json_path)
    plan = build_training_plan(context, [], [])

    assert plan["lora"]["r"] == 2
    assert plan["lora"]["target_modules"] == ["q_proj"]
    assert plan["trainer"]["max_steps"] == 1
    assert plan["trainer"]["gradient_accumulation_steps"] == 1
    assert plan["trainer"]["max_train_samples"] == 4
    assert plan["trainer"]["max_val_samples"] == 1


def test_write_training_artifacts_plan_only(tmp_path: Path, monkeypatch):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    train_path = export_dir / "enterprise_sft_train.jsonl"
    val_path = export_dir / "enterprise_sft_val.jsonl"
    manifest_path = export_dir / "manifest.json"
    _write_jsonl(train_path, [])
    _write_jsonl(val_path, [])
    manifest_path.write_text(json.dumps({"paths": {"sft_train": str(train_path), "sft_val": str(val_path)}}), encoding="utf-8")
    request_json_path = tmp_path / "training_request.json"
    request_json_path.write_text(
        json.dumps(
            {
                "job_id": "job-2",
                "tenant_id": "default",
                "dataset_name": "swu_public_docs",
                "base_model": "qwen2.5:7b",
                "manifest_path": str(manifest_path),
                "artifact_dir": str(tmp_path / "artifacts"),
                "target_model_name": "default-swu",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DOCMIND_TRAINING_SERVING_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("DOCMIND_TRAINING_SERVING_MODEL_NAME", "qwen2.5:7b")
    context = load_training_context(request_json_path)
    result = write_training_artifacts(
        context,
        plan={"publish": {"publish_ready": False}},
        executed=False,
        adapter_dir=None,
        notes="plan only",
        publish_ready=False,
        extra_metadata={"fallback_reason": "missing deps"},
    )

    assert Path(result["artifact_dir"]).exists()
    assert (context.artifact_dir / "training_result.json").exists()
    payload = json.loads((context.artifact_dir / "training_result.json").read_text(encoding="utf-8"))
    assert payload["executor_metadata"]["mode"] == "plan_only"
    assert payload["executor_metadata"]["publish_ready"] is False

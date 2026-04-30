"""Training executor abstraction for mock and remote execution backends."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings


@dataclass
class TrainingExecutionRequest:
    job_id: str
    tenant_id: str
    dataset_name: str
    base_model: str
    export_dir: str
    manifest_path: str
    target_model_name: str
    train_records: int
    val_records: int
    artifact_dir: str
    provider: str


class TrainingExecutor:
    async def execute(self, request: TrainingExecutionRequest) -> dict[str, Any]:
        raise NotImplementedError

    def validate_result(self, result: dict[str, Any]) -> dict[str, Any]:
        artifact_dir = str(result.get("artifact_dir") or "").strip()
        serving_base_url = str(result.get("serving_base_url") or "").strip()
        serving_model_name = str(result.get("serving_model_name") or "").strip()
        if not artifact_dir:
            raise ValueError("训练执行结果缺少 artifact_dir")
        if not serving_base_url:
            raise ValueError("训练执行结果缺少 serving_base_url")
        if not serving_model_name:
            raise ValueError("训练执行结果缺少 serving_model_name")
        return {
            "artifact_dir": artifact_dir,
            "serving_base_url": serving_base_url,
            "serving_model_name": serving_model_name,
            "executor_metadata": result.get("executor_metadata") or {},
            "notes": result.get("notes"),
        }


class MockTrainingExecutor(TrainingExecutor):
    async def execute(self, request: TrainingExecutionRequest) -> dict[str, Any]:
        artifact_dir = Path(request.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        adapter_manifest = {
            "job_id": request.job_id,
            "tenant_id": request.tenant_id,
            "dataset_name": request.dataset_name,
            "provider": request.provider,
            "base_model": request.base_model,
            "target_model_name": request.target_model_name,
            "train_records": request.train_records,
            "val_records": request.val_records,
            "source_export_dir": request.export_dir,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "executor": "mock",
        }
        (artifact_dir / "adapter_manifest.json").write_text(json.dumps(adapter_manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        (artifact_dir / "model_card.md").write_text(
            "\n".join(
                [
                    f"# {request.target_model_name}",
                    "",
                    f"- tenant: {request.tenant_id}",
                    f"- dataset: {request.dataset_name}",
                    f"- base_model: {request.base_model}",
                    f"- train_records: {request.train_records}",
                    f"- val_records: {request.val_records}",
                    "",
                    "该产物为 DocMind 当前阶段的训练执行占位产物，可在后续接入真实 LoRA/SFT 训练器后替换。",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        return {
            "artifact_dir": str(artifact_dir),
            "serving_base_url": settings.llm_enterprise_api_base_url or settings.llm_api_base_url,
            "serving_model_name": settings.llm_enterprise_model_name or settings.llm_model_name,
            "executor_metadata": {"executor": "mock"},
            "notes": "当前为 mock 训练执行器输出，可替换为真实训练服务。",
        }


class RemoteTrainingExecutor(TrainingExecutor):
    async def execute(self, request: TrainingExecutionRequest) -> dict[str, Any]:
        base_url = (settings.llm_training_executor_api_base_url or "").rstrip("/")
        if not base_url:
            raise ValueError("未配置训练执行器 API 地址")

        payload = {
            "job_id": request.job_id,
            "tenant_id": request.tenant_id,
            "dataset_name": request.dataset_name,
            "base_model": request.base_model,
            "export_dir": request.export_dir,
            "manifest_path": request.manifest_path,
            "target_model_name": request.target_model_name,
            "train_records": request.train_records,
            "val_records": request.val_records,
            "artifact_dir": request.artifact_dir,
            "provider": request.provider,
        }
        headers = {"Content-Type": "application/json"}
        if settings.llm_training_executor_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_training_executor_api_key}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_training_executor_timeout_seconds, connect=10.0)) as client:
            response = await client.post(f"{base_url}/train", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("训练执行器返回格式非法")
        return data


def build_training_executor(provider: str | None) -> TrainingExecutor:
    runtime_provider = (provider or settings.llm_training_provider or "mock").strip().lower()
    if runtime_provider in {"remote", "http", "api"}:
        return RemoteTrainingExecutor()
    return MockTrainingExecutor()

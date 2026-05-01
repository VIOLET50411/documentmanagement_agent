"""Training executor abstraction for mock, script, and remote backends."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import shlex
import subprocess
import sys
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


def _builtin_training_runner_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "run_lora_sft.py"


def _resolve_script_command_template(command_template: str | None = None) -> tuple[str, str]:
    configured = str(command_template or settings.llm_training_executor_script_command or "").strip()
    if configured:
        return configured, "configured"

    if not settings.llm_training_executor_builtin_runner_enabled:
        raise ValueError("未配置本地脚本训练执行器命令，且未启用内置训练脚本")

    runner_path = _builtin_training_runner_path()
    if not runner_path.exists():
        raise ValueError(f"未找到内置训练脚本: {runner_path}")

    python_executable = str(sys.executable or "").strip()
    if not python_executable:
        raise ValueError("当前 Python 解释器不可用，无法执行内置训练脚本")

    command = f"{shlex.quote(python_executable)} {shlex.quote(str(runner_path))} --request-json {{request_json_path}}"
    if settings.llm_training_executor_allow_plan_fallback:
        command += " --allow-plan-fallback"
    return command, "builtin"


def describe_training_runtime(provider: str | None = None) -> dict[str, Any]:
    configured_provider = (provider or settings.llm_training_provider or "script").strip().lower()
    builtin_runner_path = _builtin_training_runner_path()
    builtin_runner_exists = builtin_runner_path.exists()
    missing_dependencies = [
        package
        for package in ("torch", "transformers", "datasets", "peft", "accelerate", "safetensors")
        if importlib.util.find_spec(package) is None
    ]

    payload: dict[str, Any] = {
        "configured_provider": configured_provider,
        "builtin_runner_path": str(builtin_runner_path),
        "builtin_runner_exists": builtin_runner_exists,
        "allow_plan_fallback": bool(settings.llm_training_executor_allow_plan_fallback),
    }

    if configured_provider in {"remote", "http", "api"}:
        payload.update(
            {
                "resolved_provider": "remote",
                "ready": bool((settings.llm_training_executor_api_base_url or "").strip()),
                "api_base_url": str(settings.llm_training_executor_api_base_url or "").strip(),
            }
        )
        return payload

    if configured_provider in {"mock"}:
        payload.update(
            {
                "resolved_provider": "mock",
                "ready": True,
                "note": "当前配置仍可退回 mock 训练执行器，不会产出真实 LoRA/SFT 结果。",
            }
        )
        return payload

    try:
        command, source = _resolve_script_command_template()
    except ValueError as exc:
        payload.update(
            {
                "resolved_provider": "script",
                "ready": False,
                "command_source": "unavailable",
                "script_command": "",
                "dependencies_ready": False,
                "missing_dependencies": missing_dependencies,
                "reason": str(exc),
            }
        )
        return payload

    payload.update(
        {
            "resolved_provider": "script",
            "ready": builtin_runner_exists and not missing_dependencies,
            "command_source": source,
            "script_command": command,
            "dependencies_ready": not missing_dependencies,
            "missing_dependencies": missing_dependencies,
        }
    )
    if missing_dependencies:
        payload["reason"] = "missing_training_dependencies"
    return payload


class TrainingExecutor:
    async def execute(self, request: TrainingExecutionRequest) -> dict[str, Any]:
        raise NotImplementedError

    def validate_result(self, result: dict[str, Any]) -> dict[str, Any]:
        artifact_dir = str(result.get("artifact_dir") or "").strip()
        serving_base_url = str(result.get("serving_base_url") or "").strip()
        serving_model_name = str(result.get("serving_model_name") or "").strip()
        adapter_dir = str(result.get("adapter_dir") or "").strip()
        executed = bool(result.get("executed"))
        executor_metadata = result.get("executor_metadata") if isinstance(result.get("executor_metadata"), dict) else {}
        mode = str(executor_metadata.get("mode") or "").strip().lower()

        if not artifact_dir:
            raise ValueError("训练执行结果缺少 artifact_dir")
        if not serving_base_url:
            raise ValueError("训练执行结果缺少 serving_base_url")
        if not serving_model_name:
            raise ValueError("训练执行结果缺少 serving_model_name")
        if mode == "plan_only" or not executed:
            raise ValueError("训练执行器仅输出训练计划，未生成可注册产物")
        if not adapter_dir:
            raise ValueError("训练执行结果缺少 adapter_dir")
        if not Path(adapter_dir).exists():
            raise ValueError(f"训练执行结果中的 adapter_dir 不存在: {adapter_dir}")

        return {
            "artifact_dir": artifact_dir,
            "adapter_dir": adapter_dir,
            "serving_base_url": serving_base_url,
            "serving_model_name": serving_model_name,
            "executor_metadata": executor_metadata,
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
        (artifact_dir / "adapter_manifest.json").write_text(
            json.dumps(adapter_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
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
                    "该产物为 DocMind 当前阶段的占位训练产物，可在后续接入真实 LoRA/SFT 训练器后替换。",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        return {
            "artifact_dir": str(artifact_dir),
            "adapter_dir": str(artifact_dir),
            "executed": True,
            "serving_base_url": settings.llm_enterprise_api_base_url or settings.llm_api_base_url,
            "serving_model_name": settings.llm_enterprise_model_name or settings.llm_model_name,
            "executor_metadata": {"executor": "mock", "mode": "executed"},
            "notes": "当前为 mock 训练执行器输出，可替换为真实训练服务。",
        }


class ScriptTrainingExecutor(TrainingExecutor):
    async def execute(self, request: TrainingExecutionRequest) -> dict[str, Any]:
        command_template, command_source = _resolve_script_command_template()

        artifact_dir = Path(request.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        request_json_path = artifact_dir / "training_request.json"
        request_payload = {
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
        request_json_path.write_text(
            json.dumps(request_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )

        format_args = {**request_payload, "request_json_path": str(request_json_path)}
        command = command_template.format(**format_args)
        workdir = Path((settings.llm_training_executor_script_workdir or str(artifact_dir)).strip() or str(artifact_dir))
        workdir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "DOCMIND_TRAINING_REQUEST_JSON": str(request_json_path),
                "DOCMIND_TRAINING_ARTIFACT_DIR": request.artifact_dir,
                "DOCMIND_TRAINING_TARGET_MODEL_NAME": request.target_model_name,
                "DOCMIND_TRAINING_BASE_MODEL": request.base_model,
                "DOCMIND_TRAINING_DATASET_NAME": request.dataset_name,
                "DOCMIND_TRAINING_TENANT_ID": request.tenant_id,
                "DOCMIND_TRAINING_JOB_ID": request.job_id,
            }
        )

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_raw, stderr_raw = await process.communicate()
        stdout_text = stdout_raw.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_raw.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            message = stderr_text or stdout_text or f"训练脚本退出码 {process.returncode}"
            raise RuntimeError(message[-4000:])

        result_payload = self._load_result_payload(artifact_dir, stdout_text)
        metadata = result_payload.get("executor_metadata") if isinstance(result_payload.get("executor_metadata"), dict) else {}
        metadata.update(
            {
                "executor": "script",
                "command_source": command_source,
                "command": command,
                "workdir": str(workdir),
                "request_json_path": str(request_json_path),
            }
        )
        result_payload["executor_metadata"] = metadata
        if stderr_text and not result_payload.get("notes"):
            result_payload["notes"] = stderr_text[-1000:]
        return result_payload

    def _load_result_payload(self, artifact_dir: Path, stdout_text: str) -> dict[str, Any]:
        for candidate in (artifact_dir / "training_result.json", artifact_dir / "result.json"):
            if candidate.exists():
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload

        for line in reversed(stdout_text.splitlines()):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise ValueError("训练脚本未生成可解析的结果 JSON")


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
            if self._is_terminal_payload(data):
                result = self._extract_terminal_result(data)
                result["executor_metadata"] = {**(result.get("executor_metadata") or {}), "executor": "remote"}
                return result

            job_id = str((data or {}).get("job_id") or "").strip()
            status_url = str((data or {}).get("status_url") or "").strip()
            if not job_id and not status_url:
                raise ValueError("训练执行器未返回可轮询的 job_id 或 status_url")
            result = await self._poll_until_completed(client, headers=headers, base_url=base_url, job_id=job_id, status_url=status_url)
            result["executor_metadata"] = {
                **(result.get("executor_metadata") or {}),
                "executor": "remote",
                "job_id": job_id,
                "status_url": status_url or f"{base_url}/jobs/{job_id}",
            }
            return result

    async def _poll_until_completed(
        self,
        client: httpx.AsyncClient,
        *,
        headers: dict[str, str],
        base_url: str,
        job_id: str,
        status_url: str,
    ) -> dict[str, Any]:
        timeout_seconds = max(int(settings.llm_training_executor_timeout_seconds), 30)
        poll_interval = max(int(settings.llm_training_executor_poll_interval_seconds), 1)
        attempts = max(1, math.ceil(timeout_seconds / poll_interval))
        resolved_status_url = status_url or f"{base_url}/jobs/{job_id}"
        for _ in range(attempts):
            response = await client.get(resolved_status_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if self._is_terminal_payload(payload):
                return self._extract_terminal_result(payload)
            status = str((payload or {}).get("status") or "").strip().lower()
            if status in {"failed", "error", "cancelled", "canceled", "killed"}:
                error_message = str((payload or {}).get("error") or (payload or {}).get("message") or "训练执行器任务失败")
                raise RuntimeError(error_message)
        raise TimeoutError(f"训练执行器在 {timeout_seconds}s 内未完成任务")

    def _is_terminal_payload(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("artifact_dir") and payload.get("serving_base_url") and payload.get("serving_model_name"):
            return True
        status = str(payload.get("status") or "").strip().lower()
        return status in {"completed", "succeeded", "success", "done"}

    def _extract_terminal_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        if not isinstance(result_payload, dict):
            raise ValueError("训练执行器返回格式非法")
        return result_payload


def build_training_executor(provider: str | None) -> TrainingExecutor:
    runtime_provider = (provider or settings.llm_training_provider or "script").strip().lower()
    if runtime_provider in {"script", "local-script", "shell"}:
        return ScriptTrainingExecutor()
    if runtime_provider in {"remote", "http", "api"}:
        return RemoteTrainingExecutor()
    if runtime_provider == "mock":
        return MockTrainingExecutor()
    return MockTrainingExecutor()

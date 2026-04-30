from pathlib import Path

import pytest

from app.training.executor import MockTrainingExecutor, TrainingExecutionRequest, TrainingExecutor, build_training_executor


@pytest.mark.asyncio
async def test_mock_training_executor_writes_artifacts(tmp_path: Path):
    request = TrainingExecutionRequest(
        job_id="job-1",
        tenant_id="default",
        dataset_name="swu_public_docs",
        base_model="qwen2.5:7b",
        export_dir=str(tmp_path / "export"),
        manifest_path=str(tmp_path / "export" / "manifest.json"),
        target_model_name="default-swu",
        train_records=24,
        val_records=3,
        artifact_dir=str(tmp_path / "artifacts"),
        provider="mock",
    )

    result = await MockTrainingExecutor().execute(request)

    assert (tmp_path / "artifacts" / "adapter_manifest.json").exists()
    assert (tmp_path / "artifacts" / "model_card.md").exists()
    assert result["artifact_dir"] == str(tmp_path / "artifacts")


def test_training_executor_validate_result_requires_required_fields():
    executor = TrainingExecutor()
    with pytest.raises(ValueError, match="artifact_dir"):
        executor.validate_result({"serving_base_url": "http://localhost", "serving_model_name": "qwen"})


def test_build_training_executor_supports_remote_aliases():
    assert build_training_executor("mock").__class__.__name__ == "MockTrainingExecutor"
    assert build_training_executor("remote").__class__.__name__ == "RemoteTrainingExecutor"
    assert build_training_executor("api").__class__.__name__ == "RemoteTrainingExecutor"

"""Admin API sub-package — split from monolithic admin.py for maintainability.

Re-exports frequently monkeypatched symbols for test backward compatibility.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin.documents import router as documents_router
from app.api.v1.admin.security import router as security_router
from app.api.v1.admin.training import router as training_router
from app.api.v1.admin.training_data import router as training_data_router
from app.api.v1.admin.system import router as system_router
from app.api.v1.admin.evaluation import router as evaluation_router

# Re-export symbols that integration tests monkeypatch via `app.api.v1.admin.*`
from app.dependencies import get_db, get_redis, get_minio_client  # noqa: F401
from app.api.v1.admin._helpers import (  # noqa: F401
    _seed_runtime_task,
    _get_runtime_task_payload,
    _serialize_training_job,
    _serialize_registry_model,
    REPORTS_DIR,
    PUBLIC_DATASETS_DIR,
)

router = APIRouter()
router.include_router(documents_router)
router.include_router(security_router)
router.include_router(training_router)
router.include_router(training_data_router)
router.include_router(system_router)
router.include_router(evaluation_router)

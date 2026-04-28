"""Platform readiness scoring service."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.document import Document
from app.services.runtime_evaluation_service import RuntimeEvaluationService


class PlatformReadinessService:
    def __init__(self, db: AsyncSession, redis_client):
        self.db = db
        self.redis = redis_client

    async def evaluate(self, tenant_id: str) -> dict:
        checks: list[dict] = []

        checks.append({"id": "postgres", "ok": await self._check_postgres(), "weight": 25, "message": "PostgreSQL 连接检查"})
        checks.append({"id": "redis", "ok": await self._check_redis(), "weight": 10, "message": "Redis 连接检查"})
        checks.append({"id": "documents", "ok": await self._check_documents_present(tenant_id), "weight": 10, "message": "存在可用文档样本"})
        checks.append({"id": "ingestion", "ok": await self._check_ingestion_health(tenant_id), "weight": 20, "message": "文档处理状态健康"})
        checks.append({"id": "security", "ok": self._check_security_flags(), "weight": 10, "message": "安全能力开关基线"})
        checks.append({"id": "eval_runtime", "ok": await self._check_runtime_metrics(tenant_id), "weight": 10, "message": "运行时评估指标可用"})
        checks.append({"id": "eval_report", "ok": self._check_eval_report(tenant_id), "weight": 5, "message": "离线评估报告可读取"})
        checks.append({"id": "registration_policy", "ok": self._check_registration_policy(), "weight": 10, "message": "注册策略与邮箱域名策略"})

        total_weight = sum(item["weight"] for item in checks)
        score = round(sum(item["weight"] for item in checks if item["ok"]) / total_weight * 100, 2) if total_weight else 0.0
        blockers = [item for item in checks if not item["ok"]]
        return {
            "score": score,
            "ready": score >= 85 and not blockers,
            "checks": checks,
            "blockers": blockers,
        }

    async def _check_postgres(self) -> bool:
        try:
            value = await self.db.scalar(select(text("1")))
            return int(value or 0) == 1
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    async def _check_redis(self) -> bool:
        if self.redis is None:
            return False
        try:
            pong = await self.redis.ping()
            return bool(pong)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    async def _check_documents_present(self, tenant_id: str) -> bool:
        count = await self.db.scalar(select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id))
        return int(count or 0) > 0

    async def _check_ingestion_health(self, tenant_id: str) -> bool:
        total = int(
            await self.db.scalar(
                select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id, Document.status.in_(["ready", "partial_failed", "failed"]))
            )
            or 0
        )
        if total == 0:
            return False
        success = int(
            await self.db.scalar(
                select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id, Document.status.in_(["ready", "partial_failed"]))
            )
            or 0
        )
        return (success / total) >= 0.8

    def _check_security_flags(self) -> bool:
        from app.services.security_policy_service import SecurityPolicyService

        base_enabled = bool(settings.pii_masking_enabled and settings.guardrails_enabled and settings.watermark_enabled)
        policy = SecurityPolicyService().evaluate()
        return bool(base_enabled and policy.get("compliant", False))

    async def _check_runtime_metrics(self, tenant_id: str) -> bool:
        metrics = await RuntimeEvaluationService(self.db, self.redis).get_metrics(tenant_id, persist_history=False)
        return metrics.get("counts", {}).get("assistant_total", 0) > 0

    def _check_eval_report(self, tenant_id: str) -> bool:
        base = Path(__file__).resolve()
        candidates = [
            base.parents[2] / "reports" / f"evaluation_{tenant_id}.json",  # container: /app/reports
            base.parents[3] / "reports" / f"evaluation_{tenant_id}.json",  # local repo root
        ]
        return any(path.exists() for path in candidates)

    def _check_registration_policy(self) -> bool:
        # 企业内部默认关闭公开注册；若开启公开注册，必须同时配置 allowlist 与 blocklist。
        if not settings.auth_allow_public_registration:
            return True
        return bool(settings.auth_allowlist_domain_list and settings.auth_blocklist_domain_list)

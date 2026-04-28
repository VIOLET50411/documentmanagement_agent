"""Retrieval backend observability service."""

from __future__ import annotations

from datetime import datetime, timezone


class RetrievalObservabilityService:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def record(
        self,
        tenant_id: str,
        backend: str,
        *,
        success: bool,
        empty: bool,
        timeout: bool,
        latency_ms: int,
        error: str | None = None,
    ) -> None:
        if self.redis is None:
            return
        key = f"metrics:retrieval:{tenant_id}:backend:{backend}"
        now = datetime.now(timezone.utc).isoformat()
        await self.redis.hincrby(key, "requests", 1)
        await self.redis.hincrby(key, "success", 1 if success else 0)
        await self.redis.hincrby(key, "empty", 1 if empty else 0)
        await self.redis.hincrby(key, "errors", 0 if success else 1)
        await self.redis.hincrby(key, "timeouts", 1 if timeout else 0)
        await self.redis.hset(
            key,
            mapping={
                "last_latency_ms": str(latency_ms),
                "last_error": (error or "")[:500],
                "updated_at": now,
            },
        )
        await self.redis.expire(key, 30 * 24 * 3600)

        latency_key = f"metrics:retrieval:{tenant_id}:latency:{backend}"
        await self.redis.lpush(latency_key, str(latency_ms))
        await self.redis.ltrim(latency_key, 0, 999)
        await self.redis.expire(latency_key, 30 * 24 * 3600)

    async def summary(self, tenant_id: str) -> dict:
        if self.redis is None:
            return {"backends": {}, "source": "none"}
        backends = {}
        for backend in ("es", "milvus", "graph"):
            key = f"metrics:retrieval:{tenant_id}:backend:{backend}"
            data = await self.redis.hgetall(key)
            requests = int(data.get("requests", 0) or 0)
            success = int(data.get("success", 0) or 0)
            errors = int(data.get("errors", 0) or 0)
            timeouts = int(data.get("timeouts", 0) or 0)
            empty = int(data.get("empty", 0) or 0)
            latency_rows = await self.redis.lrange(f"metrics:retrieval:{tenant_id}:latency:{backend}", 0, 999)
            latencies = []
            for row in latency_rows:
                try:
                    latencies.append(int(row))
                except (TypeError, ValueError):
                    continue
            backends[backend] = {
                "requests": requests,
                "success_rate": round(success / requests, 4) if requests else 0.0,
                "error_rate": round(errors / requests, 4) if requests else 0.0,
                "timeout_rate": round(timeouts / requests, 4) if requests else 0.0,
                "empty_rate": round(empty / requests, 4) if requests else 0.0,
                "latency_p95_ms": _p95(latencies),
                "last_latency_ms": int(data.get("last_latency_ms", 0) or 0),
                "last_error": data.get("last_error") or "",
                "updated_at": data.get("updated_at"),
            }
        return {"backends": backends, "source": "redis"}


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(0.95 * (len(ordered) - 1))))
    return ordered[index]

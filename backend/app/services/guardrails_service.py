"""Guardrails sidecar integration with fail-open/fail-closed control."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class GuardrailsService:
    def __init__(self):
        self.enabled = settings.guardrails_enabled
        self.sidecar_url = (settings.guardrails_sidecar_url or "").rstrip("/")
        self.fail_closed = settings.guardrails_fail_closed

    async def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "available": False, "status": "disabled"}
        if not self.sidecar_url:
            return {"enabled": True, "available": False, "status": "degraded", "reason": "missing_sidecar_url"}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(self.sidecar_url + "/health")
                resp.raise_for_status()
            return {"enabled": True, "available": True, "status": "online"}
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"enabled": True, "available": False, "status": "degraded", "error": str(exc)}

    async def check_input(self, content: str) -> dict[str, Any]:
        if not self.enabled or not self.sidecar_url:
            return {"safe": not self.fail_closed, "issues": [], "mode": "bypass"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(self.sidecar_url + "/check/input", json={"text": content})
                resp.raise_for_status()
                payload = resp.json()
            return {
                "safe": bool(payload.get("safe", True)),
                "issues": payload.get("issues", []),
                "reason": payload.get("reason", ""),
                "mode": "sidecar",
            }
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            if self.fail_closed:
                return {"safe": False, "issues": ["guardrails_sidecar_unavailable"], "reason": str(exc), "mode": "fail_closed"}
            return {"safe": True, "issues": [], "reason": str(exc), "mode": "degraded"}

    async def check_output(self, content: str) -> dict[str, Any]:
        if not self.enabled or not self.sidecar_url:
            return {"safe": not self.fail_closed, "issues": [], "mode": "bypass"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(self.sidecar_url + "/check/output", json={"text": content})
                resp.raise_for_status()
                payload = resp.json()
            return {
                "safe": bool(payload.get("safe", True)),
                "issues": payload.get("issues", []),
                "reason": payload.get("reason", ""),
                "mode": "sidecar",
            }
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            if self.fail_closed:
                return {"safe": False, "issues": ["guardrails_sidecar_unavailable"], "reason": str(exc), "mode": "fail_closed"}
            return {"safe": True, "issues": [], "reason": str(exc), "mode": "degraded"}

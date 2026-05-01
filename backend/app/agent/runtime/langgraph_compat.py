"""Compatibility helpers for LangGraph native checkpoint backends."""

from __future__ import annotations

from importlib import metadata
from typing import Any

from app.config import settings


def native_checkpoint_support_status() -> dict[str, Any]:
    """Return whether native LangGraph Postgres checkpoints can be used safely."""
    enabled = bool(settings.runtime_langgraph_native_checkpoint_enabled)
    versions = {
        "langgraph": _safe_version("langgraph"),
        "langgraph_checkpoint_postgres": _safe_version("langgraph-checkpoint-postgres"),
        "langgraph_checkpoint": _safe_version("langgraph-checkpoint"),
    }
    if not enabled:
        return {
            "enabled": False,
            "compatible": False,
            "available": False,
            "reason": "disabled_by_config",
            "versions": versions,
        }

    langgraph_version = versions["langgraph"]
    if not langgraph_version:
        return {
            "enabled": True,
            "compatible": False,
            "available": False,
            "reason": "langgraph_not_installed",
            "versions": versions,
        }

    major, minor = _parse_major_minor(langgraph_version)
    if major == 0 and minor < 5:
        return {
            "enabled": True,
            "compatible": False,
            "available": False,
            "reason": "langgraph_checkpoint_postgres_requires_langgraph_gte_0_5",
            "versions": versions,
        }

    if not versions["langgraph_checkpoint_postgres"]:
        return {
            "enabled": True,
            "compatible": False,
            "available": False,
            "reason": "checkpoint_postgres_not_installed",
            "versions": versions,
        }

    return {
        "enabled": True,
        "compatible": True,
        "available": True,
        "reason": "ok",
        "versions": versions,
    }


def _safe_version(package_name: str) -> str | None:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def _parse_major_minor(version_text: str) -> tuple[int, int]:
    parts = str(version_text).split(".")
    try:
        major = int(parts[0])
    except (TypeError, ValueError, IndexError):
        major = 0
    try:
        minor = int(parts[1])
    except (TypeError, ValueError, IndexError):
        minor = 0
    return major, minor

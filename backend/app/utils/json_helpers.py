"""Shared JSON parsing helpers to eliminate duplication across services."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def safe_load_json(raw: str | None) -> dict[str, Any]:
    """Parse a JSON string into a dict, returning ``{}`` on any failure."""
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def safe_load_json_file(path: Path) -> dict[str, Any]:
    """Read a JSON file and return its content as a dict, or ``{}`` on failure."""
    if not path.exists():
        return {}
    try:
        return safe_load_json(path.read_text(encoding="utf-8"))
    except OSError:
        return {}

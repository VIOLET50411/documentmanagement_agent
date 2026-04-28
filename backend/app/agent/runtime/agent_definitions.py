"""Agent definition loading and controlled local extension support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "agent_type",
    "when_to_use",
    "tools",
    "disallowed_tools",
    "model",
    "effort",
    "permission_mode",
    "max_turns",
    "background",
    "isolation",
    "memory_scope",
}

RESTRICTED_FIELDS = {"global_hooks", "external_connectors", "system_permissions"}


DEFAULT_AGENT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "supervisor": {
        "agent_type": "supervisor",
        "when_to_use": "default routing and orchestration",
        "tools": ["retrieval.search"],
        "disallowed_tools": [],
        "model": "fallback-rules",
        "effort": "low",
        "permission_mode": "enforced",
        "max_turns": 1,
        "background": False,
        "isolation": "tenant",
        "memory_scope": "session",
    },
    "data": {
        "agent_type": "data",
        "when_to_use": "structured analytics and count/stat requests",
        "tools": ["text2sql"],
        "disallowed_tools": [],
        "model": "fallback-rules",
        "effort": "medium",
        "permission_mode": "enforced",
        "max_turns": 1,
        "background": False,
        "isolation": "tenant",
        "memory_scope": "session",
    },
}


def load_agent_definitions(extensions_dir: str | Path | None, *, enabled_tools: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Load built-in and controlled extension agent definitions."""
    definitions = {name: value.copy() for name, value in DEFAULT_AGENT_DEFINITIONS.items()}
    if extensions_dir is None:
        return _apply_tool_filter(definitions, enabled_tools)

    path = Path(extensions_dir)
    if not path.exists() or not path.is_dir():
        return _apply_tool_filter(definitions, enabled_tools)

    for file_path in path.glob("*.json"):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _is_valid_extension(payload):
            continue
        agent_type = payload["agent_type"]
        definitions[agent_type] = payload

    return _apply_tool_filter(definitions, enabled_tools)


def _is_valid_extension(payload: dict[str, Any]) -> bool:
    keys = set(payload.keys())
    if any(key in keys for key in RESTRICTED_FIELDS):
        return False
    if not REQUIRED_FIELDS.issubset(keys):
        return False
    if not isinstance(payload.get("tools"), list) or not isinstance(payload.get("disallowed_tools"), list):
        return False
    return True


def _apply_tool_filter(definitions: dict[str, dict[str, Any]], enabled_tools: set[str] | None) -> dict[str, dict[str, Any]]:
    if not enabled_tools:
        return definitions
    filtered: dict[str, dict[str, Any]] = {}
    for name, item in definitions.items():
        tools = [tool for tool in item.get("tools", []) if tool in enabled_tools]
        clone = item.copy()
        clone["tools"] = tools
        filtered[name] = clone
    return filtered

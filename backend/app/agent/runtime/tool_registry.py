"""Tool registry and unified tool result envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RetryPolicy:
    max_retries: int = 1
    backoff_seconds: float = 0.3


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    timeout_ms: int = 8000
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    risk_level: str = "low"


@dataclass(slots=True)
class ToolResultEnvelope:
    ok: bool
    data: Any = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "warnings": self.warnings,
            "duration_ms": self.duration_ms,
            "degraded": self.degraded,
        }


class ToolRegistry:
    """Registry of allowed runtime tools."""

    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def resolve(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def list(self) -> list[ToolSpec]:
        return list(self._specs.values())


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="text2sql",
            description="Generate safe SQL for analytics in rules mode",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"sql": {"type": "string"}, "results": {"type": "array"}}},
            enabled=True,
            timeout_ms=5000,
            risk_level="medium",
        )
    )
    registry.register(
        ToolSpec(
            name="retrieval.search",
            description="Hybrid retrieval over ES/Milvus/Graph backends",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"results": {"type": "array"}}},
            enabled=True,
            timeout_ms=8000,
            risk_level="low",
        )
    )
    registry.register(
        ToolSpec(
            name="calculator",
            description="Basic numeric calculator utility",
            input_schema={"type": "object", "properties": {"expression": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"value": {"type": "number"}}},
            enabled=True,
            timeout_ms=1500,
            risk_level="low",
        )
    )
    registry.register(
        ToolSpec(
            name="summarizer",
            description="Rules-mode summarization helper",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            enabled=True,
            timeout_ms=3000,
            risk_level="low",
        )
    )
    registry.register(
        ToolSpec(
            name="python_repl",
            description="Sandboxed python execution for data post-processing",
            input_schema={"type": "object", "properties": {"code": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"output": {"type": "string"}, "error": {"type": "string"}}},
            enabled=True,
            timeout_ms=5000,
            risk_level="high",
        )
    )
    registry.register(
        ToolSpec(
            name="erp_connector",
            description="ERP connector placeholder tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            enabled=False,
            timeout_ms=8000,
            risk_level="high",
        )
    )
    return registry

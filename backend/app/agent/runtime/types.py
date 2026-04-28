"""Core runtime data structures for AgentRuntime v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class RuntimeRequest:
    """Runtime input envelope."""

    query: str
    thread_id: str | None
    search_type: str
    user_context: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ToolCallRecord:
    """A single tool execution record inside a runtime iteration."""

    tool_name: str
    decision: str
    duration_ms: int
    ok: bool
    reason: str | None = None
    degraded: bool = False


@dataclass(slots=True)
class RuntimeState:
    """Canonical runtime state."""

    session_id: str
    tenant_id: str
    query: str
    rewritten_query: str = ""
    intent: str = "qa"
    selected_agent: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    trace_id: str = ""
    iteration: int = 0
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeEvent:
    """Runtime event for SSE streaming."""

    status: str
    source: str
    sequence_num: int
    trace_id: str
    event_id: str
    data: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    fallback_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "source": self.source,
            "sequence_num": self.sequence_num,
            "trace_id": self.trace_id,
            "event_id": self.event_id,
            "degraded": self.degraded,
            "fallback_reason": self.fallback_reason,
        }
        payload.update(self.data)
        return payload

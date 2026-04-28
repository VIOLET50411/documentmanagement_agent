"""Optional Langfuse tracing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings

try:  # pragma: no cover - optional dependency
    from langfuse import Langfuse
except ImportError:  # pragma: no cover - optional dependency
    Langfuse = None


@dataclass
class LangfuseSpan:
    trace: Any | None = None
    generation: Any | None = None
    enabled: bool = False

    def finish(self, *, output: Any = None, metadata: dict | None = None, usage: dict | None = None, level: str = "DEFAULT") -> None:
        if not self.enabled:
            return
        try:  # pragma: no cover - optional dependency path
            if self.generation is not None and hasattr(self.generation, "end"):
                kwargs: dict[str, Any] = {"metadata": metadata or {}}
                if output is not None:
                    kwargs["output"] = output
                if usage:
                    kwargs["usage_details"] = usage
                self.generation.end(**kwargs)
            if self.trace is not None and hasattr(self.trace, "update"):
                self.trace.update(level=level)
        except Exception:
            return

    def fail(self, *, error: str, metadata: dict | None = None) -> None:
        payload = {"error": error}
        if metadata:
            payload.update(metadata)
        self.finish(metadata=payload, level="ERROR")


class LangfuseObserver:
    """Minimal optional wrapper over the Langfuse SDK."""

    def __init__(self):
        self.enabled = bool(Langfuse and settings.langfuse_public_key and settings.langfuse_secret_key and settings.langfuse_host)
        self._client = None
        if not self.enabled:
            return
        try:  # pragma: no cover - optional dependency path
            self._client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        except Exception:
            self.enabled = False
            self._client = None

    def start_generation(
        self,
        *,
        name: str,
        model: str,
        provider: str,
        input_payload: Any,
        metadata: dict | None = None,
    ) -> LangfuseSpan:
        if not self.enabled or self._client is None:
            return LangfuseSpan(enabled=False)
        try:  # pragma: no cover - optional dependency path
            trace = self._client.trace(name=name, metadata={"provider": provider, **(metadata or {})})
            generation = trace.generation(
                name=name,
                model=model,
                input=input_payload,
                metadata=metadata or {},
            )
            return LangfuseSpan(trace=trace, generation=generation, enabled=True)
        except Exception:
            return LangfuseSpan(enabled=False)

    def flush(self) -> None:
        if not self.enabled or self._client is None:
            return
        try:  # pragma: no cover - optional dependency path
            self._client.flush()
        except Exception:
            return

"""Document embedder with real model support and deterministic fallback."""

from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Any

import httpx
from redis import Redis
import structlog

from app.config import settings
from app.services.canary_router import in_canary_bucket

logger = structlog.get_logger("docmind.embedder")

# Default dimension for real embedding models (BGE-M3 = 1024, nomic-embed-text = 768)
# The local fallback uses a much smaller dim for lightweight operation.
REAL_EMBEDDING_DIM = 1024
LOCAL_FALLBACK_DIM = 64
EMBEDDING_DIM_KEY = "embedding:detected_dim"


class DocumentEmbedder:
    """Generate dense and sparse vectors using real embedding models with local fallback."""

    def __init__(self, dense_dim: int | None = None):
        self.provider = (settings.embedding_provider or "local").lower()
        self.base_url = (settings.embedding_api_base_url or "").rstrip("/")
        self.model = settings.embedding_model_name or "BAAI/bge-m3"
        self.api_key = settings.embedding_api_key or ""
        self.canary_percent = settings.embedding_canary_percent
        self.canary_seed = settings.embedding_canary_seed
        self._last_health_ok: bool | None = None
        self._remote_circuit_open_until = 0.0
        self._real_dim: int | None = self._read_detected_dim()  # Detected from remote call, persisted in Redis

        # Set dense_dim: prefer real model dim, fall back to local
        if dense_dim is not None:
            self.dense_dim = dense_dim
        elif self._real_dim:
            self.dense_dim = self._real_dim
        elif self._should_use_remote("__init__"):
            self.dense_dim = REAL_EMBEDDING_DIM
        else:
            self.dense_dim = LOCAL_FALLBACK_DIM

    def embed(self, chunks: list) -> list:
        """Generate both dense and sparse vectors for each chunk."""
        # Batch embedding for efficiency when using remote provider
        if self._should_use_remote("batch"):
            texts = [chunk.get("content", "") for chunk in chunks]
            batch_results = self._embed_remote_batch(texts)
            if batch_results and len(batch_results) == len(chunks):
                for chunk, vectors in zip(chunks, batch_results):
                    chunk["dense_vector"] = vectors
                    chunk["sparse_vector"] = self._sparse_from_tokens(chunk.get("content", ""))
                return chunks

        # Single-doc fallback
        for chunk in chunks:
            vectors = self.embed_query(chunk.get("content", ""), tenant_key=chunk.get("tenant_id") or "default")
            chunk["dense_vector"] = vectors["dense"]
            chunk["sparse_vector"] = vectors["sparse"]
        return chunks

    def embed_query(self, query: str, tenant_key: str = "default") -> dict:
        """Embed a single query for retrieval."""
        if self._should_use_remote(tenant_key):
            remote = self._embed_remote(query)
            if remote:
                self._update_detected_dim(len(remote))
                sparse = self._sparse_from_tokens(query)
                return {"dense": remote, "sparse": sparse}

        return self._embed_local(query)

    def local_embed_query(self, query: str) -> dict:
        """Force local deterministic embedding (used by heavy fallback loops)."""
        return self._embed_local(query)

    def _embed_local(self, query: str) -> dict:
        """Deterministic local embedding using character-level hashing."""
        tokens = [token.lower() for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query)]
        target_dim = self._real_dim or self.dense_dim or LOCAL_FALLBACK_DIM
        base_dim = min(target_dim, LOCAL_FALLBACK_DIM)
        if not tokens:
            return {"dense": [0.0] * target_dim, "sparse": {}}

        dense = [0.0] * base_dim
        sparse: dict[str, float] = {}
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            sparse[token] = sparse.get(token, 0.0) + 1.0
            for index in range(base_dim):
                byte_index = index % len(digest)
                dense[index] += digest[byte_index] / 255.0

        norm = math.sqrt(sum(value * value for value in dense)) or 1.0
        dense = [round(value / norm, 6) for value in dense]
        if target_dim > base_dim:
            # Keep deterministic signal in the leading local dims, zero-pad to real model dimension.
            dense.extend([0.0] * (target_dim - base_dim))
        elif target_dim < len(dense):
            dense = dense[:target_dim]

        token_count = len(tokens)
        sparse = {token: round(weight / token_count, 6) for token, weight in sparse.items()}
        return {"dense": dense, "sparse": sparse}

    def _sparse_from_tokens(self, text: str) -> dict[str, float]:
        tokens = [token.lower() for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text)]
        if not tokens:
            return {}
        sparse: dict[str, float] = {}
        for token in tokens:
            sparse[token] = sparse.get(token, 0.0) + 1.0
        count = len(tokens)
        return {token: round(value / count, 6) for token, value in sparse.items()}

    def _should_use_remote(self, tenant_key: str) -> bool:
        if self.provider in {"rule"}:
            return False
        if not self.base_url:
            return False
        # For "local" and "fallback" providers, still try remote if base_url is configured
        if self.provider in {"local", "fallback"} and not self.base_url:
            return False
        return True

    def remote_health(self) -> dict[str, Any]:
        if not self.base_url:
            self._last_health_ok = False
            return {"enabled": False, "available": False, "mode": "local"}
        try:
            with httpx.Client(timeout=httpx.Timeout(4.0, connect=2.0)) as client:
                if self.provider == "ollama":
                    resp = client.get(self.base_url.replace("/v1", "") + "/api/tags")
                    resp.raise_for_status()
                    tags = [item.get("name", "") for item in resp.json().get("models", [])]
                    has_model = any(tag.startswith(self.model.split(":")[0]) for tag in tags)
                    self._last_health_ok = has_model
                    return {"enabled": True, "available": has_model, "mode": "ollama", "model_pulled": has_model}
                resp = client.post(self.base_url + "/embeddings", json={"model": self.model, "input": "health-check"}, headers=self._headers())
                resp.raise_for_status()
                self._last_health_ok = True
                return {"enabled": True, "available": True, "mode": self.provider}
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._last_health_ok = False
            return {"enabled": True, "available": False, "mode": "degraded", "error": str(exc)}

    def _embed_remote(self, text: str) -> list[float] | None:
        if self._remote_circuit_open_until > time.monotonic():
            return None
        try:
            timeout = httpx.Timeout(10.0, connect=2.0)
            with httpx.Client(timeout=timeout) as client:
                if self.provider == "ollama":
                    endpoint = self.base_url.replace("/v1", "") + "/api/embeddings"
                    resp = client.post(endpoint, json={"model": self.model, "prompt": text})
                    resp.raise_for_status()
                    payload = resp.json()
                    vector = payload.get("embedding")
                    if isinstance(vector, list):
                        self._update_detected_dim(len(vector))
                        return [float(x) for x in vector]
                    return None

                endpoint = self.base_url + "/embeddings"
                resp = client.post(endpoint, json={"model": self.model, "input": text}, headers=self._headers())
                resp.raise_for_status()
                payload: dict[str, Any] = resp.json()
                data = payload.get("data") or []
                if not data:
                    return None
                vector = (data[0] or {}).get("embedding")
                if isinstance(vector, list):
                    self._update_detected_dim(len(vector))
                    return [float(x) for x in vector]
                return None
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("embedder.remote_failed", error=str(exc))
            self._remote_circuit_open_until = time.monotonic() + 30.0
            return None

    def _embed_remote_batch(self, texts: list[str]) -> list[list[float]] | None:
        """Batch embed multiple texts in one request."""
        if self._remote_circuit_open_until > time.monotonic():
            return None
        if not texts:
            return []

        try:
            timeout = httpx.Timeout(30.0, connect=3.0)
            with httpx.Client(timeout=timeout) as client:
                if self.provider == "ollama":
                    # Ollama doesn't support batch in /api/embeddings, process sequentially
                    results = []
                    endpoint = self.base_url.replace("/v1", "") + "/api/embeddings"
                    for text in texts:
                        resp = client.post(endpoint, json={"model": self.model, "prompt": text})
                        resp.raise_for_status()
                        vector = resp.json().get("embedding")
                        if isinstance(vector, list):
                            self._update_detected_dim(len(vector))
                            results.append([float(x) for x in vector])
                        else:
                            return None
                    return results

                # OpenAI-compatible batch endpoint
                endpoint = self.base_url + "/embeddings"
                resp = client.post(endpoint, json={"model": self.model, "input": texts}, headers=self._headers())
                resp.raise_for_status()
                payload = resp.json()
                data = payload.get("data") or []
                if len(data) != len(texts):
                    return None
                results = []
                for item in sorted(data, key=lambda x: x.get("index", 0)):
                    vector = item.get("embedding")
                    if isinstance(vector, list):
                        self._update_detected_dim(len(vector))
                        results.append([float(x) for x in vector])
                    else:
                        return None
                return results
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("embedder.batch_remote_failed", error=str(exc))
            self._remote_circuit_open_until = time.monotonic() + 30.0
            return None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _update_detected_dim(self, dim: int) -> None:
        if dim <= 0:
            return
        self._real_dim = dim
        self.dense_dim = dim
        self._persist_detected_dim(dim)

    def _read_detected_dim(self) -> int | None:
        try:
            client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1)
            value = client.get(EMBEDDING_DIM_KEY)
            client.close()
            if value is None:
                return None
            parsed = int(value)
            return parsed if parsed > 0 else None
        except (OSError, RuntimeError, TypeError, ValueError):
            return None

    def _persist_detected_dim(self, dim: int) -> None:
        try:
            client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1)
            client.set(EMBEDDING_DIM_KEY, str(dim), ex=7 * 24 * 3600)
            client.close()
        except (OSError, RuntimeError, TypeError, ValueError):
            # Persist best-effort only; local process state still keeps detected dim.
            return

"""Deterministic canary routing for model/provider rollout."""

from __future__ import annotations

import hashlib


def in_canary_bucket(key: str, *, percent: int, seed: str) -> bool:
    """Return True if key falls into canary percentage bucket."""
    bounded = max(0, min(int(percent or 0), 100))
    if bounded >= 100:
        return True
    if bounded <= 0:
        return False
    digest = hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < bounded


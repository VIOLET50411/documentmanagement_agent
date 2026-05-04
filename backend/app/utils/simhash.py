"""Near-duplicate detection using SimHash (pure Python, no external deps)."""

from __future__ import annotations

import hashlib
import re


def _tokenize(text: str) -> list[str]:
    """Simple CJK + alphanumeric tokenizer with bigram expansion."""
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text.lower())
    expanded = []
    for token in tokens:
        expanded.append(token)
        if len(token) > 2 and re.search(r"[\u4e00-\u9fff]", token):
            expanded.extend(token[i : i + 2] for i in range(len(token) - 1))
    return expanded


def compute_simhash(text: str, hash_bits: int = 64) -> int:
    """Compute SimHash fingerprint for a text string."""
    tokens = _tokenize(text)
    if not tokens:
        return 0

    vector = [0] * hash_bits
    for token in tokens:
        token_hash = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(hash_bits):
            if token_hash & (1 << i):
                vector[i] += 1
            else:
                vector[i] -= 1

    fingerprint = 0
    for i in range(hash_bits):
        if vector[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(hash_a: int, hash_b: int) -> int:
    """Compute Hamming distance between two SimHash values."""
    return bin(hash_a ^ hash_b).count("1")


def is_near_duplicate(hash_a: int, hash_b: int, threshold: int = 3) -> bool:
    """Check if two hashes are near-duplicates (Hamming distance ≤ threshold)."""
    return hamming_distance(hash_a, hash_b) <= threshold

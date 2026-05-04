"""Chat history truncation to stay within LLM context windows."""

from __future__ import annotations


def truncate_history(
    messages: list[dict],
    max_tokens: int = 4000,
    chars_per_token: float = 2.0,
) -> list[dict]:
    """Keep the most recent messages whose total estimated tokens ≤ *max_tokens*.

    Uses a simple heuristic: ``len(content) / chars_per_token`` to estimate
    token count (Chinese text averages ~2 chars per token).

    The system message (index 0) is always preserved if present, and the most
    recent user message is never dropped.
    """
    if not messages:
        return []

    # Always keep the first system message if it exists.
    system_msg = None
    rest = list(messages)
    if rest and rest[0].get("role") == "system":
        system_msg = rest.pop(0)

    budget = max_tokens
    if system_msg:
        budget -= max(int(len(system_msg.get("content", "")) / chars_per_token), 1)

    selected: list[dict] = []
    used = 0
    for msg in reversed(rest):
        estimated = max(int(len(msg.get("content", "")) / chars_per_token), 1)
        if used + estimated > budget and selected:
            break
        selected.insert(0, msg)
        used += estimated

    if system_msg:
        selected.insert(0, system_msg)
    return selected

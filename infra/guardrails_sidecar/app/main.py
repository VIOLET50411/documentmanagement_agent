from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="DocMind Guardrails Sidecar", version="0.1.0")


class CheckRequest(BaseModel):
    text: str


INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+all\s+previous\s+instructions",
        r"act\s+as\s+system",
        r"system\s*prompt",
        r"请忽略.*指令",
        r"越权",
        r"bypass",
    ]
]

OUTPUT_LEAK_PATTERNS = [
    ("id_card", re.compile(r"\b\d{17}[\dXx]\b")),
    ("phone", re.compile(r"\b1\d{10}\b")),
    ("bank_card", re.compile(r"\b\d{15,19}\b")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "status": "online"}


@app.post("/check/input")
async def check_input(payload: CheckRequest) -> dict[str, Any]:
    text = payload.text or ""
    issues = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            issues.append("prompt_injection")
            break
    return {
        "safe": len(issues) == 0,
        "issues": issues,
        "reason": "blocked_by_input_guard" if issues else "ok",
    }


@app.post("/check/output")
async def check_output(payload: CheckRequest) -> dict[str, Any]:
    text = payload.text or ""
    issues = [name for name, pattern in OUTPUT_LEAK_PATTERNS if pattern.search(text)]
    return {
        "safe": len(issues) == 0,
        "issues": issues,
        "reason": "blocked_by_output_guard" if issues else "ok",
    }

"""Python REPL Tool - hardened sandboxed code execution for calculations."""

from __future__ import annotations

import io
import contextlib
import subprocess
import sys
import tempfile
from pathlib import Path


class PythonREPL:
    """Sandboxed Python execution for data calculations."""

    ALLOWED_MODULES = {"math", "statistics", "datetime", "json", "re"}

    FORBIDDEN_PATTERNS = frozenset({
        "__import__", "eval(", "exec(", "open(", "getattr(",
        "__subclasses__", "__bases__", "__class__", "subprocess",
        "os.", "sys.", "shutil.", "pathlib.", "glob.", "socket.",
        "pickle.", "marshal.", "ctypes.", "importlib.",
    })

    TIMEOUT_SECONDS = 5
    MAX_OUTPUT_CHARS = 2000

    async def execute(self, code: str) -> dict:
        """
        Execute Python code in a restricted sandbox.
        Uses a subprocess with timeout for isolation.
        Only allows safe modules (no os, sys, subprocess, etc.)
        """
        # Phase 1: static analysis — block dangerous patterns
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in code:
                return {"error": f"Forbidden pattern detected: {pattern}", "output": ""}

        # Phase 2: validate imports against allowlist
        for line in code.split("\n"):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                module = stripped.split()[1].split(".")[0]
                if module not in self.ALLOWED_MODULES:
                    return {"error": f"Module '{module}' is not allowed", "output": ""}

        # Phase 3: execute in subprocess for hard isolation
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
                cwd=tempfile.gettempdir(),
            )
            output = result.stdout[:self.MAX_OUTPUT_CHARS]
            error = result.stderr[:500] if result.returncode != 0 else None
            return {"output": output, "error": error}
        except subprocess.TimeoutExpired:
            return {"output": "", "error": "Execution timed out (5s limit)"}
        except Exception as exc:
            return {"output": "", "error": f"Execution failed: {type(exc).__name__}"}

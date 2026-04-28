"""File security scanner with optional ClamAV integration."""

from __future__ import annotations

import socket

from app.config import settings


class FileScanner:
    EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"

    def health(self) -> dict:
        if not settings.clamav_enabled:
            return {"enabled": False, "available": False, "status": "disabled"}
        try:
            with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=1.5) as sock:
                sock.sendall(b"PING\n")
                resp = sock.recv(64)
            return {"enabled": True, "available": b"PONG" in resp, "status": "online" if b"PONG" in resp else "degraded"}
        except (OSError, TimeoutError, ValueError) as exc:
            return {"enabled": True, "available": False, "status": "degraded", "error": str(exc)}

    def scan_bytes(self, content: bytes) -> dict:
        if self.EICAR_MARKER in content:
            return {"safe": False, "reason": "检测到 EICAR 测试病毒标记", "engine": "local-rule"}

        if not settings.clamav_enabled:
            return {"safe": True, "reason": "未启用 ClamAV，已执行本地规则扫描", "engine": "local-rule"}

        try:
            ok = self._clamav_scan(content)
            if ok:
                return {"safe": True, "reason": "ClamAV 扫描通过", "engine": "clamav"}
            return {"safe": False, "reason": "ClamAV 检测到可疑内容", "engine": "clamav"}
        except (OSError, TimeoutError, ValueError) as exc:
            if settings.clamav_fail_closed:
                return {"safe": False, "reason": f"ClamAV 不可用且为 fail-closed: {exc}", "engine": "clamav"}
            return {"safe": True, "reason": f"ClamAV 不可用，按降级策略放行: {exc}", "engine": "clamav-degraded"}

    def _clamav_scan(self, content: bytes) -> bool:
        with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=3.0) as sock:
            sock.sendall(b"zINSTREAM\0")
            for idx in range(0, len(content), 8192):
                chunk = content[idx : idx + 8192]
                sock.sendall(len(chunk).to_bytes(4, "big") + chunk)
            sock.sendall((0).to_bytes(4, "big"))
            reply = sock.recv(4096).decode("utf-8", errors="ignore")
        return "OK" in reply and "FOUND" not in reply

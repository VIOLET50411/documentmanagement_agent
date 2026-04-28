#!/usr/bin/env python3
"""Runtime replay/task maintenance: TTL audit and repair."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from dataclasses import asdict, dataclass
from pathlib import Path

from redis.asyncio import Redis

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings


@dataclass(slots=True)
class MaintenanceStats:
    scanned_replay_keys: int = 0
    repaired_replay_ttl: int = 0
    removed_empty_replay: int = 0
    scanned_task_keys: int = 0
    repaired_task_ttl: int = 0
    scanned_task_indexes: int = 0
    repaired_task_index_ttl: int = 0


async def _scan_keys(redis: Redis, pattern: str) -> list[str]:
    cursor = 0
    keys: list[str] = []
    while True:
        cursor, rows = await redis.scan(cursor=cursor, match=pattern, count=300)
        keys.extend(rows or [])
        if cursor == 0:
            break
    return keys


async def run_maintenance(*, cleanup_empty: bool) -> MaintenanceStats:
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    stats = MaintenanceStats()
    try:
        replay_keys = await _scan_keys(redis, "runtime:replay:*")
        for key in replay_keys:
            stats.scanned_replay_keys += 1
            ttl = await redis.ttl(key)
            if ttl < 0:
                await redis.expire(key, settings.runtime_event_replay_ttl_seconds)
                stats.repaired_replay_ttl += 1
            if cleanup_empty:
                length = await redis.llen(key)
                if length <= 0:
                    await redis.delete(key)
                    stats.removed_empty_replay += 1

        task_keys = await _scan_keys(redis, "runtime:task:*")
        for key in task_keys:
            stats.scanned_task_keys += 1
            ttl = await redis.ttl(key)
            if ttl < 0:
                await redis.expire(key, settings.runtime_task_retention_seconds)
                stats.repaired_task_ttl += 1

        index_keys = await _scan_keys(redis, "runtime:tasks:*")
        for key in index_keys:
            stats.scanned_task_indexes += 1
            ttl = await redis.ttl(key)
            if ttl < 0:
                await redis.expire(key, settings.runtime_task_retention_seconds)
                stats.repaired_task_index_ttl += 1
    finally:
        await redis.aclose()
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(description="Runtime replay/task maintenance")
    parser.add_argument("--cleanup-empty", action="store_true", help="Delete empty replay keys")
    parser.add_argument("--write-report", action="store_true", help="Write report into reports/maintenance")
    args = parser.parse_args()

    stats = await run_maintenance(cleanup_empty=args.cleanup_empty)
    payload = asdict(stats)
    print(json.dumps(payload, ensure_ascii=False))
    if args.write_report:
        report_dir = ROOT_DIR / "reports" / "maintenance"
        report_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_json = report_dir / f"runtime_maintenance_{ts}.json"
        report_md = report_dir / f"runtime_maintenance_{ts}.md"
        report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# Runtime Maintenance Report",
            "",
            f"- generated_at: {datetime.now().isoformat()}",
            f"- cleanup_empty: {bool(args.cleanup_empty)}",
            "",
            "## Stats",
            "",
        ]
        for key, value in payload.items():
            lines.append(f"- {key}: {value}")
        report_md.write_text("\n".join(lines), encoding="utf-8")
        print(str(report_json))
        print(str(report_md))


if __name__ == "__main__":
    asyncio.run(main())

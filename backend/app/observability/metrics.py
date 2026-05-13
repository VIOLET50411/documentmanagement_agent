"""Lightweight in-process metrics exporter."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self.request_counts = defaultdict(int)
        self.request_duration_sum = defaultdict(float)
        self.request_duration_count = defaultdict(int)
        self.request_duration_max = defaultdict(float)
        self.request_slow_counts = defaultdict(int)
        self.operation_duration_sum = defaultdict(float)
        self.operation_duration_count = defaultdict(int)
        self.startup_phase_duration = {}
        self.cache_hits = 0
        self.cache_misses = 0

    def record_request(self, method: str, path: str, status_code: int, duration: float, *, slow: bool = False) -> None:
        key = (method, path, str(status_code))
        duration_key = (method, path)
        with self._lock:
            self.request_counts[key] += 1
            self.request_duration_sum[duration_key] += duration
            self.request_duration_count[duration_key] += 1
            self.request_duration_max[duration_key] = max(self.request_duration_max[duration_key], duration)
            if slow:
                self.request_slow_counts[duration_key] += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1

    def record_operation(self, name: str, duration: float) -> None:
        with self._lock:
            self.operation_duration_sum[name] += duration
            self.operation_duration_count[name] += 1

    def record_startup_phase(self, name: str, duration: float) -> None:
        with self._lock:
            self.startup_phase_duration[name] = duration

    def render_prometheus(self) -> str:
        lines = [
            "# HELP docmind_http_requests_total Total HTTP requests.",
            "# TYPE docmind_http_requests_total counter",
        ]
        with self._lock:
            for (method, path, status_code), value in sorted(self.request_counts.items()):
                lines.append(
                    f'docmind_http_requests_total{{method="{method}",path="{path}",status="{status_code}"}} {value}'
                )

            lines.extend(
                [
                    "# HELP docmind_http_request_duration_seconds_avg Average request duration in seconds.",
                    "# TYPE docmind_http_request_duration_seconds_avg gauge",
                ]
            )
            for (method, path), total in sorted(self.request_duration_sum.items()):
                count = self.request_duration_count[(method, path)]
                avg = total / count if count else 0
                lines.append(
                    f'docmind_http_request_duration_seconds_avg{{method="{method}",path="{path}"}} {avg:.6f}'
                )
            lines.extend(
                [
                    "# HELP docmind_http_request_duration_seconds_max Maximum request duration in seconds.",
                    "# TYPE docmind_http_request_duration_seconds_max gauge",
                ]
            )
            for (method, path), max_duration in sorted(self.request_duration_max.items()):
                lines.append(
                    f'docmind_http_request_duration_seconds_max{{method="{method}",path="{path}"}} {max_duration:.6f}'
                )
            lines.extend(
                [
                    "# HELP docmind_http_requests_slow_total Total slow HTTP requests.",
                    "# TYPE docmind_http_requests_slow_total counter",
                ]
            )
            for (method, path), value in sorted(self.request_slow_counts.items()):
                lines.append(f'docmind_http_requests_slow_total{{method="{method}",path="{path}"}} {value}')

            lines.extend(
                [
                    "# HELP docmind_semantic_cache_hits_total Semantic cache hits.",
                    "# TYPE docmind_semantic_cache_hits_total counter",
                    f"docmind_semantic_cache_hits_total {self.cache_hits}",
                    "# HELP docmind_semantic_cache_misses_total Semantic cache misses.",
                    "# TYPE docmind_semantic_cache_misses_total counter",
                    f"docmind_semantic_cache_misses_total {self.cache_misses}",
                ]
            )

            lines.extend(
                [
                    "# HELP docmind_operation_duration_seconds_avg Average named operation duration in seconds.",
                    "# TYPE docmind_operation_duration_seconds_avg gauge",
                ]
            )
            for name, total in sorted(self.operation_duration_sum.items()):
                count = self.operation_duration_count[name]
                avg = total / count if count else 0
                lines.append(f'docmind_operation_duration_seconds_avg{{name="{name}"}} {avg:.6f}')

            lines.extend(
                [
                    "# HELP docmind_startup_phase_duration_seconds Latest startup phase duration in seconds.",
                    "# TYPE docmind_startup_phase_duration_seconds gauge",
                ]
            )
            for name, duration in sorted(self.startup_phase_duration.items()):
                lines.append(f'docmind_startup_phase_duration_seconds{{phase="{name}"}} {duration:.6f}')

        return "\n".join(lines) + "\n"

    def snapshot_request_metrics(self, *, limit: int = 10) -> list[dict[str, float | int | str]]:
        rows: list[dict[str, float | int | str]] = []
        with self._lock:
            for method, path in sorted(self.request_duration_sum.keys()):
                total = self.request_duration_sum[(method, path)]
                count = self.request_duration_count[(method, path)]
                avg = total / count if count else 0.0
                rows.append(
                    {
                        "method": method,
                        "path": path,
                        "count": count,
                        "avg_ms": round(avg * 1000, 2),
                        "max_ms": round(self.request_duration_max[(method, path)] * 1000, 2),
                        "slow_count": int(self.request_slow_counts[(method, path)]),
                    }
                )
        rows.sort(key=lambda item: (float(item["avg_ms"]), float(item["max_ms"])), reverse=True)
        return rows[: max(limit, 1)]


metrics_registry = MetricsRegistry()

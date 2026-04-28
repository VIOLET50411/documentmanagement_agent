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
        self.cache_hits = 0
        self.cache_misses = 0

    def record_request(self, method: str, path: str, status_code: int, duration: float) -> None:
        key = (method, path, str(status_code))
        duration_key = (method, path)
        with self._lock:
            self.request_counts[key] += 1
            self.request_duration_sum[duration_key] += duration
            self.request_duration_count[duration_key] += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1

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
                    "# HELP docmind_semantic_cache_hits_total Semantic cache hits.",
                    "# TYPE docmind_semantic_cache_hits_total counter",
                    f"docmind_semantic_cache_hits_total {self.cache_hits}",
                    "# HELP docmind_semantic_cache_misses_total Semantic cache misses.",
                    "# TYPE docmind_semantic_cache_misses_total counter",
                    f"docmind_semantic_cache_misses_total {self.cache_misses}",
                ]
            )

        return "\n".join(lines) + "\n"


metrics_registry = MetricsRegistry()

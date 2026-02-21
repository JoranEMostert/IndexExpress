import time
from collections import defaultdict
from typing import Any


class MetricsRegistry:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._request_stats: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"count": 0, "errors": 0, "total_s": 0.0, "max_s": 0.0}
        )
        self._tool_stats: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"count": 0, "errors": 0, "total_s": 0.0, "max_s": 0.0}
        )

    @staticmethod
    def _update_bucket(bucket: dict[str, float | int], status: str, duration_s: float) -> None:
        bucket["count"] = int(bucket["count"]) + 1
        if status != "ok":
            bucket["errors"] = int(bucket["errors"]) + 1
        bucket["total_s"] = float(bucket["total_s"]) + duration_s
        bucket["max_s"] = max(float(bucket["max_s"]), duration_s)

    def record_request(self, method: str, status: str, duration_s: float) -> None:
        self._update_bucket(self._request_stats[method], status, duration_s)

    def record_tool(self, tool_name: str, status: str, duration_s: float) -> None:
        self._update_bucket(self._tool_stats[tool_name], status, duration_s)

    @staticmethod
    def _materialize(raw: dict[str, dict[str, float | int]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, values in raw.items():
            count = int(values["count"])
            total_s = float(values["total_s"])
            out[key] = {
                "count": count,
                "errors": int(values["errors"]),
                "avg_s": round(total_s / count, 4) if count else 0.0,
                "max_s": round(float(values["max_s"]), 4),
                "total_s": round(total_s, 4),
            }
        return dict(sorted(out.items(), key=lambda item: item[0]))

    def snapshot(self) -> dict[str, Any]:
        return {
            "uptime_s": round(time.time() - self.started_at, 2),
            "requests": self._materialize(self._request_stats),
            "tools": self._materialize(self._tool_stats),
        }

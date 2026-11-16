"""Accounting: every gateway call is written to `llm_calls` and aggregated for /api/admin/llm/status."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Any, Protocol

from terrapilot.core.logging import get_logger
from terrapilot.llm.types import CallRecord

log = get_logger("llm.sink")


class CallSink(Protocol):
    def write(self, record: CallRecord) -> None: ...


class StatsSink:
    """In-process rolling stats (latency, fallback rate, cache hits) per task."""

    def __init__(self, window: int = 500):
        self._lock = threading.Lock()
        self._latency: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self._status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.records: deque[CallRecord] = deque(maxlen=window)

    def write(self, record: CallRecord) -> None:
        with self._lock:
            self._latency[record.task].append(record.latency_ms)
            self._status[record.task][record.status] += 1
            self.records.append(record)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {}
            for task, counts in self._status.items():
                lat = sorted(self._latency[task])
                total = sum(counts.values())
                out[task] = {
                    "calls": total,
                    "by_status": dict(counts),
                    "fallback_rate": round(counts.get("fallback", 0) / total, 3) if total else 0.0,
                    "p50_ms": lat[len(lat) // 2] if lat else None,
                    "p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
                }
            return out


class DbSink:
    """Writes to the `llm_calls` table; never lets an accounting failure break an LLM call."""

    def __init__(self, database_url: str):
        from terrapilot.db.engine import get_engine

        self.engine = get_engine(database_url)
        self._disabled = False

    def write(self, record: CallRecord) -> None:
        if self._disabled:
            return
        from terrapilot.db.schema import llm_calls

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    llm_calls.insert().values(
                        id=record.id,
                        ts=record.ts,
                        task=record.task,
                        provider=record.provider,
                        model=record.model,
                        prompt_version=record.prompt_version,
                        input_tokens=record.input_tokens,
                        output_tokens=record.output_tokens,
                        latency_ms=record.latency_ms,
                        status=record.status,
                        fallback_used=record.fallback_used,
                        guard_flags=record.guard_flags,
                        trace_id=record.trace_id,
                        error=record.error,
                    )
                )
        except Exception as exc:  # DB down → keep serving, log once
            self._disabled = True
            log.warning("llm_calls sink disabled", error=str(exc)[:200])


class FanoutSink:
    def __init__(self, *sinks: CallSink):
        self.sinks = list(sinks)

    def write(self, record: CallRecord) -> None:
        for sink in self.sinks:
            sink.write(record)

"""Per-model token buckets (RPM + TPM) with priority lanes, corrected from Groq's x-ratelimit headers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from terrapilot.llm.types import RateLimitInfo

MINUTE_S = 60.0


@dataclass
class _Bucket:
    capacity: float
    tokens: float
    refill_per_s: float
    updated: float

    def refill(self, now: float) -> None:
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_per_s)
        self.updated = now

    def fraction(self) -> float:
        return self.tokens / self.capacity if self.capacity else 1.0


@dataclass
class ModelLimiter:
    requests: _Bucket
    tokens: _Bucket
    blocked_until: float = 0.0
    daily_requests_remaining: int | None = None
    stats: dict[str, int] = field(default_factory=lambda: {"granted": 0, "denied": 0, "throttled_by_header": 0})


class RateLimiter:
    """Thread-safe limiter. `acquire` waits up to `max_wait_s`, otherwise returns False (caller falls back)."""

    def __init__(
        self,
        limits: dict[str, tuple[int, int]],
        low_headroom_fraction: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self.low_headroom_fraction = low_headroom_fraction
        now = clock()
        self._models: dict[str, ModelLimiter] = {}
        for model, (rpm, tpm) in limits.items():
            self._models[model] = ModelLimiter(
                requests=_Bucket(rpm, rpm, rpm / MINUTE_S, now), tokens=_Bucket(tpm, tpm, tpm / MINUTE_S, now)
            )

    def _get(self, model: str) -> ModelLimiter | None:
        return self._models.get(model)

    def try_acquire(self, model: str, est_tokens: int, lane: int) -> float:
        """Returns 0 when granted, otherwise the seconds to wait before retrying."""
        with self._lock:
            lim = self._get(model)
            if lim is None:
                return 0.0  # unknown models are not limited locally; headers still guard via 429
            now = self._clock()
            if now < lim.blocked_until:
                return lim.blocked_until - now
            lim.requests.refill(now)
            lim.tokens.refill(now)
            need_tokens = min(float(est_tokens), lim.tokens.capacity)
            low_priority = lane >= 2
            headroom = min(lim.requests.fraction(), lim.tokens.fraction())
            if low_priority and headroom < self.low_headroom_fraction:
                reserve = self.low_headroom_fraction * lim.tokens.capacity
                return max(0.05, (reserve - lim.tokens.tokens + need_tokens) / lim.tokens.refill_per_s)
            if lim.requests.tokens >= 1 and lim.tokens.tokens >= need_tokens:
                lim.requests.tokens -= 1
                lim.tokens.tokens -= need_tokens
                lim.stats["granted"] += 1
                return 0.0
            wait_req = 0.0 if lim.requests.tokens >= 1 else (1 - lim.requests.tokens) / lim.requests.refill_per_s
            wait_tok = (
                0.0 if lim.tokens.tokens >= need_tokens else (need_tokens - lim.tokens.tokens) / lim.tokens.refill_per_s
            )
            return max(wait_req, wait_tok, 0.01)

    def acquire(self, model: str, est_tokens: int, lane: int, max_wait_s: float) -> bool:
        deadline = self._clock() + max_wait_s
        while True:
            wait = self.try_acquire(model, est_tokens, lane)
            if wait == 0.0:
                return True
            if self._clock() + wait > deadline:
                lim = self._get(model)
                if lim:
                    lim.stats["denied"] += 1
                return False
            self._sleep(wait)

    def update_from_headers(self, model: str, rate: RateLimitInfo | None) -> None:
        if rate is None:
            return
        with self._lock:
            lim = self._get(model)
            if lim is None:
                return
            now = self._clock()
            lim.tokens.refill(now)
            if rate.remaining_tokens is not None:
                if rate.limit_tokens:
                    lim.tokens.capacity = float(rate.limit_tokens)
                    lim.tokens.refill_per_s = rate.limit_tokens / MINUTE_S
                if rate.remaining_tokens < lim.tokens.tokens:
                    lim.tokens.tokens = float(rate.remaining_tokens)
                    lim.stats["throttled_by_header"] += 1
            if rate.remaining_requests is not None:
                lim.daily_requests_remaining = rate.remaining_requests
            if rate.retry_after_s:
                lim.blocked_until = max(lim.blocked_until, now + rate.retry_after_s)

    def snapshot(self) -> dict[str, dict[str, float | int | None]]:
        with self._lock:
            now = self._clock()
            out: dict[str, dict[str, float | int | None]] = {}
            for model, lim in self._models.items():
                lim.requests.refill(now)
                lim.tokens.refill(now)
                out[model] = {
                    "requests_headroom": round(lim.requests.fraction(), 3),
                    "tokens_headroom": round(lim.tokens.fraction(), 3),
                    "blocked_for_s": round(max(0.0, lim.blocked_until - now), 2),
                    "daily_requests_remaining": lim.daily_requests_remaining,
                    **lim.stats,
                }
            return out


class CircuitBreaker:
    def __init__(self, failure_threshold: int, reset_after_s: float, clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.reset_after_s = reset_after_s
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            opened = self._opened_at.get(key)
            if opened is None:
                return True
            if self._clock() - opened >= self.reset_after_s:  # half-open: let one call through
                del self._opened_at[key]
                self._failures[key] = self.failure_threshold - 1
                return True
            return False

    def record(self, key: str, ok: bool) -> None:
        with self._lock:
            if ok:
                self._failures[key] = 0
                return
            self._failures[key] = self._failures.get(key, 0) + 1
            if self._failures[key] >= self.failure_threshold:
                self._opened_at[key] = self._clock()

    def state(self) -> dict[str, str]:
        with self._lock:
            return {k: "open" for k in self._opened_at}

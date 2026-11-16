"""Response cache keyed by (task, prompt version, normalised inputs) for deterministic tasks (§12.3)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Protocol


def cache_key(task: str, prompt_version: str | None, inputs: dict[str, Any], key_fields: list[str] | None) -> str:
    selected = {k: inputs.get(k) for k in key_fields} if key_fields else inputs
    blob = json.dumps({"t": task, "v": prompt_version, "i": _normalise(selected)}, sort_keys=True, default=str)
    return "tp:llm:" + hashlib.sha256(blob.encode()).hexdigest()


def _normalise(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    return value


class Cache(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any], ttl_s: float) -> None: ...


class MemoryCache:
    def __init__(self, max_entries: int = 2048):
        self.max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if time.monotonic() > expires:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: dict[str, Any], ttl_s: float) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl_s, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)


class RedisCache:
    def __init__(self, url: str):
        import redis

        self._redis = redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2)

    def get(self, key: str) -> dict[str, Any] | None:
        try:
            raw = self._redis.get(key)
        except Exception:
            return None
        return json.loads(raw) if raw else None

    def set(self, key: str, value: dict[str, Any], ttl_s: float) -> None:
        try:
            self._redis.set(key, json.dumps(value), ex=max(1, int(ttl_s)))
        except Exception:
            return

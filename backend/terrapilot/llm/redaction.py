"""Privacy: pseudonymise names/IDs before sending, re-hydrate after; enforce never_send (§2.2, §12.3)."""

from __future__ import annotations

import hashlib
from typing import Any


class RedactionError(ValueError):
    pass


class Pseudonymiser:
    def __init__(self, fields: list[str], never_send: list[str]):
        self.fields = set(fields)
        self.never_send = set(never_send)
        self._forward: dict[str, str] = {}
        self._reverse: dict[str, str] = {}

    def _token(self, field: str, value: str) -> str:
        if value in self._forward:
            return self._forward[value]
        digest = hashlib.sha256(f"{field}:{value}".encode()).hexdigest()[:6]
        token = f"<{field}_{digest}>"
        self._forward[value] = token
        self._reverse[token] = value
        return token

    def redact(self, inputs: Any) -> Any:
        if isinstance(inputs, dict):
            out: dict[str, Any] = {}
            for k, v in inputs.items():
                if k in self.never_send:
                    raise RedactionError(f"field '{k}' must never be sent to a cloud LLM")
                if k in self.fields and isinstance(v, str) and v:
                    out[k] = self._token(k, v)
                else:
                    out[k] = self.redact(v)
            return out
        if isinstance(inputs, list):
            return [self.redact(v) for v in inputs]
        if isinstance(inputs, str):
            for original, token in self._forward.items():
                inputs = inputs.replace(original, token)
            return inputs
        return inputs

    def rehydrate(self, value: Any) -> Any:
        if isinstance(value, str):
            for token, original in self._reverse.items():
                value = value.replace(token, original)
            return value
        if isinstance(value, dict):
            return {k: self.rehydrate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.rehydrate(v) for v in value]
        return value

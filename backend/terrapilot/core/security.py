"""PIN hashing (PBKDF2, stdlib) and JWT helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

import jwt

from terrapilot.core.timeutil import utcnow

_ALGO = "pbkdf2_sha256"


def hash_pin(pin: str, iterations: int, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)
    return f"{_ALGO}${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), base64.b64decode(salt_b64), int(iters))
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def create_token(subject: str, role: str, secret: str, algorithm: str, ttl_min: int, **claims: Any) -> str:
    now = utcnow()
    payload = {"sub": subject, "role": role, "iat": now, "exp": now + timedelta(minutes=ttl_min), **claims}
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, secret: str, algorithm: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=[algorithm])

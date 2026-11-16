"""guard_events audit rows (§13.1 audit layer): every block, refusal, redaction or fallback taken by a guard."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from terrapilot.core.timeutil import utcnow


def guard_row(
    layer: str, rule_id: str, action: str, detail: dict[str, Any], text: str = "", ts: datetime | None = None
) -> dict[str, Any]:
    return {
        "id": f"GE-{uuid.uuid4().hex[:16]}",
        "ts": ts or utcnow(),
        "layer": layer,
        "rule_id": rule_id,
        "input_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:32] if text else None,
        "action": action,
        "detail": detail,
    }


def persist_guard(conn: Any, row: dict[str, Any]) -> None:
    from sqlalchemy import insert

    from terrapilot.db.schema import guard_events

    conn.execute(insert(guard_events).values(**row))

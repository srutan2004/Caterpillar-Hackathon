"""Where tick outputs go: WS messages over Redis pub/sub (relayed by the API), rows into Postgres, or memory."""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from typing import Any, Protocol

from terrapilot.core.logging import get_logger
from terrapilot.domain.models import Advisory
from terrapilot.domain.ws import AdvisoryMessage, AlertMessage, StateDiffMessage, WsMessage
from terrapilot.edge.pipeline import TickOutput

log = get_logger("edge.sinks")
SNAPSHOT_TTL_S = 600


def flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v and not key.endswith(("sensitivity", "ppe")):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


class Sink(Protocol):
    def publish(self, machine_id: str, messages: list[WsMessage]) -> None: ...

    def persist(self, table: str, rows: list[dict[str, Any]]) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.messages: list[WsMessage] = []
        self.rows: dict[str, list[dict[str, Any]]] = {}

    def publish(self, machine_id: str, messages: list[WsMessage]) -> None:
        self.messages.extend(messages)

    def persist(self, table: str, rows: list[dict[str, Any]]) -> None:
        self.rows.setdefault(table, []).extend(rows)


class RedisDbSink:
    """Publishes to Redis channel `tp:ws:machine:{id}` (the API relays it) and writes rows to Postgres."""

    def __init__(self, redis_url: str, database_url: str | None = None, raw_stream: bool = True):
        import redis

        self.redis = redis.Redis.from_url(redis_url)
        self.raw_stream = raw_stream
        self.engine = None
        if database_url:
            from terrapilot.db.engine import get_engine

            self.engine = get_engine(database_url)

    def publish(self, machine_id: str, messages: list[WsMessage]) -> None:
        pipe = self.redis.pipeline()
        for m in messages:
            pipe.publish(f"tp:ws:machine:{machine_id}", m.model_dump_json())
        try:
            pipe.execute()
        except Exception as exc:
            log.warning("redis publish failed", error=str(exc)[:120])

    def snapshot(self, machine_id: str, state: dict[str, Any], open_alerts: list[dict[str, Any]], ttl_s: int) -> None:
        """Latest fused state + open alerts, so REST snapshots and late WS joiners see the machine immediately."""
        try:
            self.redis.set(f"tp:state:{machine_id}", json.dumps(state, default=str), ex=ttl_s)
            self.redis.set(f"tp:alerts:{machine_id}", json.dumps(open_alerts, default=str), ex=ttl_s)
        except Exception:
            pass

    def raw(self, machine_id: str, frame_json: str, maxlen: int) -> None:
        if self.raw_stream:
            with contextlib.suppress(Exception):
                self.redis.xadd(f"tp:raw:{machine_id}", {"frame": frame_json}, maxlen=maxlen, approximate=True)

    def persist(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows or self.engine is None:
            return
        from sqlalchemy.dialects.postgresql import insert

        from terrapilot.db.schema import metadata

        t = metadata.tables[table]
        stmt = insert(t).values(rows)
        pk = [c.name for c in t.primary_key.columns]
        if pk:
            stmt = stmt.on_conflict_do_update(
                index_elements=pk, set_={c: stmt.excluded[c] for c in rows[0] if c not in pk}
            )
        try:
            with self.engine.begin() as conn:
                conn.execute(stmt)
        except Exception as exc:
            log.warning("persist failed", table=table, error=str(exc)[:200])


class Publisher:
    """Turns TickOutputs into WS messages (throttled state diffs, alerts, advisories) and DB rows."""

    def __init__(self, machine_id: str, sink: Sink, throttle_ms: float):
        self.machine_id = machine_id
        self.sink = sink
        self.throttle_s = throttle_ms / 1000
        self.last_sent: dict[str, Any] = {}
        self.last_ts: datetime | None = None
        self.seq = 0
        self.open_alerts: dict[str, dict[str, Any]] = {}

    def handle(self, out: TickOutput, force_state: bool = False) -> None:
        msgs: list[WsMessage] = []
        if out.state and (
            force_state or self.last_ts is None or (out.ts - self.last_ts).total_seconds() >= self.throttle_s
        ):
            flat = flatten(out.state)
            changes = {k: v for k, v in flat.items() if self.last_sent.get(k) != v}
            full = self.last_ts is None
            if changes:
                self.seq += 1
                msgs.append(
                    StateDiffMessage(ts=out.ts, machine_id=self.machine_id, seq=self.seq, changes=changes, full=full)
                )
                self.last_sent.update(changes)
            self.last_ts = out.ts
        for ev in out.alerts:
            msgs.append(AlertMessage(ts=out.ts, event=ev))
            if ev.phase == "clear":
                self.open_alerts.pop(ev.alert.id, None)
            else:
                self.open_alerts[ev.alert.id] = ev.model_dump(mode="json")
        snap = getattr(self.sink, "snapshot", None)
        if snap is not None and msgs:
            snap(self.machine_id, self.last_sent, list(self.open_alerts.values()), SNAPSHOT_TTL_S)
        for adv in out.advisories:
            msgs.append(AdvisoryMessage(ts=out.ts, advisory=Advisory.model_validate(adv)))
        if msgs:
            self.sink.publish(self.machine_id, msgs)
        alert_rows = [
            {
                "id": e.alert.id,
                "machine_id": e.alert.machine_id,
                "rule_id": e.alert.rule_id,
                "severity": e.alert.severity,
                "opened_at": e.alert.opened_at,
                "escalated_at": e.alert.escalated_at,
                "cleared_at": e.alert.cleared_at,
                "acked_by": None,
                "context": json.dumps({"params": e.alert.params, "source": "live"}),
            }
            for e in out.alerts
            if e.phase != "update"
        ]
        self.sink.persist("alerts", alert_rows)
        self.sink.persist(
            "behavior_events",
            [
                {
                    "id": b.id,
                    "machine_id": b.machine_id,
                    "operator_id": b.operator_id,
                    "task_id": None,
                    "kind": b.kind,
                    "start_ts": b.start_ts,
                    "end_ts": b.end_ts,
                    "metrics": json.dumps(b.metrics),
                    "cost": json.dumps(b.cost),
                    "detector": b.detector,
                    "score": b.score,
                }
                for b in out.behavior
            ],
        )
        for clip in out.clips:
            self.sink.persist("blackbox_clips", [clip.clip])
            self.sink.persist("incidents", [clip.incident])

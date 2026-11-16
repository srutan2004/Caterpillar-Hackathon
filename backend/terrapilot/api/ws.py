"""WebSocket gateway skeleton (§9.2, §9.3). Phase 2 adds state diffs, alerts and advisories from the
edge process; Phase 1 authenticates, sends a `notice` hello and heartbeats, and relays anything
published on Redis channel `tp:ws:machine:{id}` so the contract can be exercised end to end.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from terrapilot.api.deps import ws_principal
from terrapilot.core.config import get_config
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.domain.ws import NoticeMessage

router = APIRouter()
WS_POLICY_VIOLATION = 1008


async def _relay_redis(ws: WebSocket, channel: str) -> None:
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return
    client = aioredis.from_url(get_settings().redis_url)
    try:
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message.get("type") == "message":
                data = message["data"]
                await ws.send_text(data.decode() if isinstance(data, bytes) else str(data))
    except Exception:
        return  # Redis unavailable: heartbeats still flow
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


@router.websocket("/ws/machines/{machine_id}")
async def machine_ws(ws: WebSocket, machine_id: str) -> None:
    cfg = get_config()
    try:
        ws_principal(cfg, ws.query_params.get("token"))
    except HTTPException:
        await ws.close(code=WS_POLICY_VIOLATION)
        return
    await ws.accept()
    hello = NoticeMessage(ts=utcnow(), code="connected", message_key="app.empty", params={"machine_id": machine_id})
    await ws.send_text(hello.model_dump_json())
    # late joiners get the latest state and open alerts immediately (snapshot kept by the edge publisher)
    from terrapilot.api.routers.live import live_snapshot
    from terrapilot.domain.ws import AlertMessage, StateDiffMessage

    flat, open_alerts = live_snapshot(machine_id)
    if flat:
        await ws.send_text(
            StateDiffMessage(ts=utcnow(), machine_id=machine_id, seq=0, changes=flat, full=True).model_dump_json()
        )
    for ev in open_alerts:
        await ws.send_text(AlertMessage.model_validate({"ts": utcnow(), "event": ev}).model_dump_json())
    relay = asyncio.create_task(_relay_redis(ws, f"tp:ws:machine:{machine_id}"))
    try:
        while True:
            try:
                incoming = await asyncio.wait_for(ws.receive_text(), timeout=cfg.app.api.ws.heartbeat_s)
                if incoming == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "ts": utcnow().isoformat()}))
            except TimeoutError:
                beat = NoticeMessage(ts=utcnow(), code="heartbeat", message_key="app.empty")
                await ws.send_text(beat.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        relay.cancel()

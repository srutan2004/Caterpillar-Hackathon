"""Machine-to-machine proximity (§10.4.3). Each machine broadcasts pose/heading/speed/envelope over Redis
(standing in for V2V radio); every machine computes pairwise CPA/TTC against the peers it hears.

Pure geometry plus a small transport shim, so the edge keeps working when Redis is down (it simply hears
no peers). Haul-road crossing and blind-spot reversing are the two rules that escalate.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any

from terrapilot.twin.proximity import time_to_radius

SECONDS_PER_HOUR = 3600.0
KPH_PER_MS = 3.6
EPS = 1e-9  # relative speed below which closest-approach time is meaningless


@dataclass
class Beacon:
    machine_id: str
    machine_class: str
    x: float
    y: float
    heading_deg: float
    speed_kph: float
    envelope_m: float
    reversing: bool
    ts: float

    def velocity(self) -> tuple[float, float]:
        v = self.speed_kph / KPH_PER_MS * (-1.0 if self.reversing else 1.0)
        rad = math.radians(self.heading_deg)
        return v * math.cos(rad), v * math.sin(rad)


@dataclass
class PeerRisk:
    machine_id: str
    machine_class: str
    distance_m: float
    gap_m: float  # distance minus both envelopes
    ttc_s: float | None
    cpa_m: float
    closing: bool
    zone: str | None
    blind_spot: bool
    tier: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_pair(own: Beacon, peer: Beacon, cfg: dict[str, Any]) -> PeerRisk:
    px, py = peer.x - own.x, peer.y - own.y
    ovx, ovy = own.velocity()
    pvx, pvy = peer.velocity()
    rvx, rvy = pvx - ovx, pvy - ovy  # relative velocity of the peer
    distance = math.hypot(px, py)
    gap = max(distance - own.envelope_m - peer.envelope_m, 0.0)
    a = rvx**2 + rvy**2
    t_cpa = max(0.0, -(px * rvx + py * rvy) / a) if a > EPS else 0.0
    cpa = math.hypot(px + rvx * t_cpa, py + rvy * t_cpa)
    radius = own.envelope_m + peer.envelope_m
    ttc = time_to_radius((px, py), (rvx, rvy), radius)
    closing = (px * rvx + py * rvy) < 0
    zones, ttcs = cfg["zones_m"], cfg["ttc_s"]
    zone = next((t for t in ("warning", "caution", "advisory") if gap < float(zones[t])), None)
    # is the peer inside our reversing arc (directly behind us)?
    bearing = (math.degrees(math.atan2(py, px)) - own.heading_deg + 540) % 360 - 180
    blind = own.reversing and abs(abs(bearing) - 180) <= float(cfg["blind_spot_deg"]) / 2
    tier = "normal"
    if zone == "warning" or (ttc is not None and ttc <= float(ttcs["warning"])):
        tier = "warning"
    elif zone == "caution" or (ttc is not None and ttc <= float(ttcs["caution"])):
        tier = "caution"
    elif zone == "advisory":
        tier = "advisory"
    if blind and tier == "advisory":
        tier = "caution"  # reversing into someone you cannot see is worse than the distance alone suggests
    return PeerRisk(
        peer.machine_id,
        peer.machine_class,
        round(distance, 1),
        round(gap, 1),
        None if ttc is None else round(ttc, 1),
        round(cpa, 1),
        closing,
        zone,
        blind,
        tier,
    )


class P2PLink:
    """Redis pub/sub transport. `publish` broadcasts our beacon; `peers` returns the fresh ones."""

    def __init__(self, cfg: dict[str, Any], site_id: str, redis_url: str | None = None):
        self.cfg = cfg
        self.site_id = site_id
        self.key = str(cfg["channel"]).format(site_id=site_id)
        self.redis: Any = None
        if redis_url:
            try:
                import redis

                self.redis = redis.Redis.from_url(redis_url, socket_timeout=0.3)
            except Exception:
                self.redis = None
        self.local: dict[str, Beacon] = {}

    def publish(self, beacon: Beacon) -> None:
        self.local[beacon.machine_id] = beacon
        if self.redis is None:
            return
        try:
            self.redis.hset(self.key, beacon.machine_id, json.dumps(asdict(beacon)))
            self.redis.expire(self.key, int(float(self.cfg["stale_after_s"]) * 10))
        except Exception:
            return

    def peers(self, own_id: str, now: float | None = None) -> list[Beacon]:
        now = now if now is not None else time.time()
        stale = float(self.cfg["stale_after_s"])
        out: list[Beacon] = []
        raw: dict[str, Any] = {}
        if self.redis is not None:
            try:
                raw = {k.decode(): json.loads(v) for k, v in self.redis.hgetall(self.key).items()}
            except Exception:
                raw = {}
        for b in self.local.values():
            raw.setdefault(b.machine_id, asdict(b))
        for mid, data in raw.items():
            if mid == own_id or now - float(data["ts"]) > stale:
                continue
            out.append(Beacon(**data))
        return out

    def assess(self, own: Beacon, now: float | None = None) -> list[PeerRisk]:
        risks = [assess_pair(own, p, self.cfg) for p in self.peers(own.machine_id, now)]
        order = {"warning": 3, "caution": 2, "advisory": 1, "normal": 0}
        return sorted([r for r in risks if r.tier != "normal"], key=lambda r: (-order[r.tier], r.gap_m))


def beacon_from_state(
    machine_id: str, machine_class: str, state: dict[str, Any], envelope_m: float, ts: float
) -> Beacon:
    pose = state.get("pose") or {}
    speed = float((state.get("motion") or {}).get("ground_speed_kph") or 0.0)
    return Beacon(
        machine_id=machine_id,
        machine_class=machine_class,
        x=float(pose.get("x") or 0.0),
        y=float(pose.get("y") or 0.0),
        heading_deg=float(pose.get("heading_deg") or 0.0),
        speed_kph=abs(speed),
        envelope_m=envelope_m,
        reversing=speed < 0,
        ts=ts,
    )

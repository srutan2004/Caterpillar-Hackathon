"""Black box (§10.4.8): ring buffer of recent frames; on a trigger, persist pre + post frames and open an
automatic incident. Triggers: warning-tier alert, IMU G-spike, manual mark."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Capture:
    clip_id: str
    trigger: str
    t0: datetime
    kind: str
    severity: str
    pre: list[dict[str, Any]]
    post: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinishedClip:
    clip: dict[str, Any]
    incident: dict[str, Any]
    frames: list[dict[str, Any]]


class BlackBox:
    def __init__(
        self, machine_id: str, tick_hz: float, frame_hz: float, pre_s: float, post_s: float, out_dir: Path | None
    ):
        self.machine_id = machine_id
        self.decimate = max(1, round(tick_hz / frame_hz))
        self.pre = deque[dict[str, Any]](maxlen=max(1, int(pre_s * frame_hz)))
        self.post_frames = max(1, int(post_s * frame_hz))
        self.out_dir = out_dir
        self.active: list[Capture] = []
        self._n = 0
        self._clips = 0

    def push(self, frame: dict[str, Any]) -> list[FinishedClip]:
        self._n += 1
        if self._n % self.decimate:
            return []
        done: list[FinishedClip] = []
        for cap in list(self.active):
            cap.post.append(frame)
            if len(cap.post) >= self.post_frames:
                self.active.remove(cap)
                done.append(self._finish(cap))
        self.pre.append(frame)
        return done

    def trigger(
        self, reason: str, t0: datetime, kind: str, severity: str, context: dict[str, Any] | None = None
    ) -> str:
        if any(c.trigger == reason for c in self.active):
            return next(c.clip_id for c in self.active if c.trigger == reason)
        self._clips += 1
        clip_id = f"BB-{self.machine_id}-{int(t0.timestamp())}-{self._clips}"
        self.active.append(Capture(clip_id, reason, t0, kind, severity, list(self.pre), context=context or {}))
        return clip_id

    def _finish(self, cap: Capture) -> FinishedClip:
        frames = cap.pre + cap.post
        uri = None
        if self.out_dir is not None:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            path = self.out_dir / f"{cap.clip_id}.jsonl"
            path.write_text("\n".join(json.dumps(f, default=str) for f in frames), encoding="utf-8")
            uri = f"blackbox/{path.name}"
        pre_s = (cap.t0 - _ts(frames[0])).total_seconds() if frames else 0.0
        post_s = (_ts(frames[-1]) - cap.t0).total_seconds() if frames else 0.0
        clip = {
            "id": cap.clip_id,
            "machine_id": self.machine_id,
            "trigger_rule_id": cap.trigger,
            "t0": cap.t0,
            "pre_s": round(pre_s, 2),
            "post_s": round(post_s, 2),
            "frames_uri": uri,
            "media_uri": None,
        }
        incident = {
            "id": f"IN-{cap.clip_id}",
            "machine_id": self.machine_id,
            "operator_id": cap.context.get("operator_id"),
            "site_id": cap.context.get("site_id"),
            "kind": cap.kind,
            "severity": cap.severity,
            "source": "auto",
            "occurred_at": cap.t0,
            "location": json.dumps(cap.context.get("location") or {}),
            "description": cap.context.get("description", cap.trigger),
            "root_cause": None,
            "blackbox_clip_id": cap.clip_id,
            "status": "new",
            "reviewer_id": None,
        }
        return FinishedClip(clip, incident, frames)

    def flush(self) -> list[FinishedClip]:
        done = [self._finish(c) for c in self.active]
        self.active = []
        return done


def _ts(frame: dict[str, Any]) -> datetime:
    ts = frame["ts"]
    return ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))

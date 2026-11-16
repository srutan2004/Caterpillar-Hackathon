"""Shared planning context (§10.14, §10.15): the business clock, observable machine state and lookups.

Everything here reads observable tables (or the live Redis snapshot when a machine is running); nothing reads
ground truth. One context is built per request/plan run so table reads are cached across helpers.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from terrapilot.core import clock
from terrapilot.core.config import ConfigBundle
from terrapilot.ml.data import Tables
from terrapilot.ml.features import TaskFeatureBuilder

SECONDS_PER_HOUR = 3600.0


class PlanningContext:
    def __init__(
        self,
        cfg: ConfigBundle,
        tables: Tables | None = None,
        now: datetime | None = None,
        data_dir: Path | None = None,
        live_state: bool = True,
    ):
        self.cfg = cfg
        self.t = tables or Tables(data_dir)
        self.data_dir = data_dir
        self.tz = ZoneInfo(str(cfg.app.site_calendar["timezone"]))
        self.now = now or clock.now(self.tz)
        self.live_state = live_state

    # ------------------------------------------------------------------ cached lookups
    @cached_property
    def features(self) -> TaskFeatureBuilder:
        return TaskFeatureBuilder(self.cfg, self.t)

    @cached_property
    def machines(self) -> pd.DataFrame:
        return self.t.get("machines").set_index("id")

    @cached_property
    def tasks(self) -> pd.DataFrame:
        return self.t.get("tasks")

    def task(self, task_id: str) -> dict[str, Any]:
        rows = self.tasks[self.tasks["id"] == task_id]
        if rows.empty:
            raise KeyError(task_id)
        return _clean(rows.iloc[0].to_dict())

    def manifest_raw(self, machine_id: str) -> dict[str, Any]:
        return self.cfg.manifests_raw[str(self.machines.loc[machine_id, "manifest_id"])]

    def manifest_id(self, machine_id: str) -> str:
        return str(self.machines.loc[machine_id, "manifest_id"])

    # ------------------------------------------------------------------ machine state now
    def _live(self, machine_id: str) -> dict[str, Any]:
        if not self.live_state:
            return {}
        try:
            import redis

            from terrapilot.core.settings import get_settings

            r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.3)
            raw = r.get(f"tp:state:{machine_id}")
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def energy_state(self, machine_id: str) -> dict[str, Any]:
        """SoC (electric) or fuel % now: live snapshot if the machine is running, else the latest log row."""
        powertrain = str(self.machines.loc[machine_id, "powertrain"])
        live = self._live(machine_id)
        if powertrain == "electric":
            soc = live.get("battery.soc")
            if soc is None:
                log = self.t.get("battery_log")
                log = log[(log["machine_id"] == machine_id) & (log["ts"] <= pd.Timestamp(self.now))]
                soc = float(log.sort_values("ts").iloc[-1]["soc"]) if not log.empty else None
            return {
                "powertrain": powertrain,
                "soc": None if soc is None else float(soc),
                "source": "live" if live else "log",
            }
        fuel = live.get("fuel.level_pct")
        if fuel is None:
            log = self.t.get("fuel_log")
            log = log[log["machine_id"] == machine_id]
            fuel = float(log.sort_values("date").iloc[-1]["fuel_pct_end"]) * 100 if not log.empty else None
        return {
            "powertrain": powertrain,
            "fuel_pct": None if fuel is None else float(fuel),
            "source": "live" if live else "log",
        }

    def health_index(self, machine_id: str) -> float:
        h = self.features.machine_health(machine_id)
        return 1.0 if math.isnan(h) else float(h)

    @cached_property
    def maintenance_alerts(self) -> pd.DataFrame:
        df = self.t.get("maintenance_alerts")
        return (
            df
            if not df.empty
            else pd.DataFrame(columns=["id", "machine_id", "component", "tier", "state", "eta", "sensor_ids"])
        )

    def open_maintenance_alerts(self, machine_id: str) -> list[dict[str, Any]]:
        df = self.maintenance_alerts
        closed = {"resolved", "false_alarm"}
        rows = df[(df["machine_id"] == machine_id) & (~df["state"].isin(closed))]
        return [_clean(r) for r in rows.to_dict("records")]

    def latest_walkaround(self, machine_id: str) -> dict[str, Any] | None:
        df = self.t.get("walkarounds")
        if df.empty:
            return None
        start_of_day = pd.Timestamp(self.now).tz_convert(self.tz).normalize().tz_convert("UTC")
        rows = df[(df["machine_id"] == machine_id) & (df["ts"] >= start_of_day) & (df["ts"] <= pd.Timestamp(self.now))]
        return _clean(rows.sort_values("ts").iloc[-1].to_dict()) if not rows.empty else None

    def cert_status(self, operator_id: str | None, machine_id: str) -> tuple[str, list[dict[str, Any]]]:
        """valid | expiring | expired | missing for the manifest's required modules."""
        if not operator_id:
            return "missing", []
        training = self.manifest_raw(machine_id).get("training") or {}
        required = list(training.get("required_modules") or [])
        grace = float(training.get("expiry_grace_days") or 0)
        certs = self.t.get("certifications")
        mine = certs[certs["user_id"] == operator_id] if not certs.empty else pd.DataFrame()
        worst, detail = "valid", []
        order = ["valid", "expiring", "expired", "missing"]
        for mod in required:
            row = mine[mine["module_id"] == mod].sort_values("expires_at").tail(1) if not mine.empty else mine
            if row.empty:
                status = "missing"
                expires = None
            else:
                expires = pd.Timestamp(row.iloc[0]["expires_at"])
                days = (expires - pd.Timestamp(self.now)).total_seconds() / 86400
                status = "expired" if days < 0 else "expiring" if days <= grace else "valid"
            detail.append(
                {"module": mod, "status": status, "expires_at": None if expires is None else expires.isoformat()}
            )
            if order.index(status) > order.index(worst):
                worst = status
        return worst, detail

    # ------------------------------------------------------------------ calendar
    def shift_bounds(self, day: datetime | None = None) -> tuple[datetime, datetime]:
        shift = self.cfg.app.site_calendar["shift"]
        local = pd.Timestamp(day or self.now).tz_convert(self.tz).normalize()
        h, m = (int(x) for x in str(shift["start_local"]).split(":"))
        start = local + pd.Timedelta(hours=h, minutes=m)
        end = start + pd.Timedelta(hours=float(shift["length_h"]))
        return start.tz_convert("UTC").to_pydatetime(), end.tz_convert("UTC").to_pydatetime()

    def breaks(self, day: datetime | None = None) -> list[tuple[datetime, datetime]]:
        start, _ = self.shift_bounds(day)
        out = []
        for b in self.cfg.app.site_calendar["shift"]["breaks"]:
            b0 = start + timedelta(hours=float(b["at_h"]))
            out.append((b0, b0 + timedelta(minutes=float(b["minutes"]))))
        return out


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
            out[k] = None
        elif isinstance(v, pd.Timestamp):
            out[k] = v.to_pydatetime()
        elif hasattr(v, "tolist") and not isinstance(v, str):
            out[k] = v.tolist()
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ shared, time-boxed table cache for the API
_SHARED: dict[str, Any] = {"tables": None, "at": 0.0}


def shared_context(cfg: ConfigBundle, now: datetime | None = None) -> PlanningContext:
    """A context whose table reads are shared across requests for `app.refresh.shift_s` seconds."""
    import time

    ttl = float(cfg.app.refresh.get("shift_s", 60))
    if _SHARED["tables"] is None or time.monotonic() - float(_SHARED["at"]) > ttl:
        _SHARED["tables"], _SHARED["at"] = Tables(), time.monotonic()
    return PlanningContext(cfg, _SHARED["tables"], now=now)


def invalidate_shared() -> None:
    _SHARED["tables"] = None

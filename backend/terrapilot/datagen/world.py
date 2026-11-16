"""Org entities (§7.3 Org): sites, zones, geofences (incl. 3D buried utilities), design surfaces, chargers."""

from __future__ import annotations

import json
import string
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.datagen.context import GenContext


def short(site_id: str) -> str:
    return site_id.removeprefix("site_")


def _rect(cx: float, cy: float, w: float, h: float) -> list[list[float]]:
    return [
        [round(cx - w / 2, 1), round(cy - h / 2, 1)],
        [round(cx + w / 2, 1), round(cy - h / 2, 1)],
        [round(cx + w / 2, 1), round(cy + h / 2, 1)],
        [round(cx - w / 2, 1), round(cy + h / 2, 1)],
    ]


def generate_world(ctx: GenContext) -> None:
    rng = ctx.rng("world")
    geo = ctx.world["geo"]
    sites, zones, fences, surfaces, chargers = [], [], [], [], []
    utility_n = overhead_n = 0
    zone_soils: dict[str, str] = {}
    for s in ctx.world["sites"]:
        sid, extent = s["id"], float(s["extent_m"])
        sites.append(
            {
                "id": sid,
                "name": s["name"],
                "type": s["type"],
                "climate_zone": s["climate"],
                "altitude_m": s["altitude_m"],
                "tz": ctx.world["timezone"],
                "lat": s["lat"],
                "lon": s["lon"],
                "geom": json.dumps(
                    {
                        "type": "Polygon",
                        "frame": "local_m",
                        "origin": [s["lat"], s["lon"]],
                        "coordinates": [_rect(0, 0, extent, extent)],
                    }
                ),
            }
        )
        soils, weights = list(s["soil_mix"]), np.array(list(s["soil_mix"].values()), dtype=float)
        letters = iter(string.ascii_uppercase)
        for kind, count in s["zones"].items():
            for n in range(1, int(count) + 1):
                zid = f"{short(sid)}-{kind}{n}"
                cx, cy = rng.uniform(-extent / 3, extent / 3, size=2)
                w, h = rng.uniform(extent / 10, extent / 5, size=2)
                soil = str(rng.choice(soils, p=weights / weights.sum()))
                ds_id = None
                if kind == "dig":
                    ds_id = f"DS-{short(sid)}-grid-{next(letters)}"
                    surfaces.append(
                        _design_surface(rng, ds_id, sid, zid, cx, cy, w, h, float(geo["design_surface_cell_m"]))
                    )
                zones.append(
                    {
                        "id": zid,
                        "site_id": sid,
                        "kind": kind,
                        "soil": soil,
                        "polygon": json.dumps({"coordinates": [_rect(cx, cy, w, h)]}),
                        "design_surface_id": ds_id,
                    }
                )
                zone_soils[zid] = soil
                if kind == "exclusion":
                    fences.append(
                        {
                            "id": f"EXC-{zid}",
                            "site_id": sid,
                            "kind": "exclusion",
                            "geom3d": json.dumps({"polygon": _rect(cx, cy, w, h)}),
                            "clearance_m": 0.0,
                            "depth_m": None,
                            "depth_uncertainty_m": None,
                            "height_m": None,
                            "source": "surveyed",
                        }
                    )
        sources = list(geo["utility_source_mix"])
        src_w = np.array(list(geo["utility_source_mix"].values()), dtype=float)
        for _ in range(int(s.get("buried_utilities", 0))):
            utility_n += 1
            source = str(rng.choice(sources, p=src_w / src_w.sum()))
            depth = rng.uniform(geo["utility_depth_m"]["min"], geo["utility_depth_m"]["max"])
            start = rng.uniform(-extent / 2, extent / 2, size=2)
            heading = rng.uniform(0, np.pi)
            length = rng.uniform(extent / 4, extent / 1.5)
            end = start + length * np.array([np.cos(heading), np.sin(heading)])
            fences.append(
                {
                    "id": f"U-{utility_n:02d}",
                    "site_id": sid,
                    "kind": "utility_buried",
                    "geom3d": json.dumps(
                        {
                            "polyline": [
                                [round(start[0], 1), round(start[1], 1), round(-depth, 2)],
                                [round(end[0], 1), round(end[1], 1), round(-depth, 2)],
                            ]
                        }
                    ),
                    "clearance_m": round(
                        rng.uniform(geo["utility_clearance_m"]["min"], geo["utility_clearance_m"]["max"]), 2
                    ),
                    "depth_m": round(depth, 2),
                    "depth_uncertainty_m": geo["utility_depth_uncertainty_m"][source],
                    "height_m": None,
                    "source": source,
                }
            )
        for _ in range(int(s.get("overhead_lines", 0))):
            overhead_n += 1
            height = rng.uniform(geo["overhead_height_m"]["min"], geo["overhead_height_m"]["max"])
            y = rng.uniform(-extent / 2, extent / 2)
            fences.append(
                {
                    "id": f"OL-{overhead_n:02d}",
                    "site_id": sid,
                    "kind": "overhead_line",
                    "geom3d": json.dumps(
                        {
                            "polyline": [
                                [-extent / 2, round(y, 1), round(height, 1)],
                                [extent / 2, round(y, 1), round(height, 1)],
                            ]
                        }
                    ),
                    "clearance_m": round(
                        rng.uniform(geo["overhead_clearance_m"]["min"], geo["overhead_clearance_m"]["max"]), 1
                    ),
                    "depth_m": None,
                    "depth_uncertainty_m": None,
                    "height_m": round(height, 1),
                    "source": "as_built",
                }
            )
        for st in s.get("charging_stations", []):
            power = max(
                (
                    float(m.energy.get("charge_power_kw_by_station", {}).get(st["kind"], 0))
                    for m in ctx.cfg.manifests.values()
                ),
                default=0.0,
            )
            chargers.append(
                {
                    "id": st["id"],
                    "site_id": sid,
                    "kind": st["kind"],
                    "power_kw": power,
                    "position": json.dumps(
                        {"xy": [round(float(v), 1) for v in rng.uniform(-extent / 3, extent / 3, 2)]}
                    ),
                }
            )

    ctx.emit("sites", pd.DataFrame(sites))
    ctx.emit("zones", pd.DataFrame(zones))
    ctx.emit("geofences", pd.DataFrame(fences))
    ctx.emit("design_surfaces", pd.DataFrame(surfaces))
    ctx.emit("charging_stations", pd.DataFrame(chargers, columns=["id", "site_id", "kind", "power_kw", "position"]))
    ctx.state["zone_soil"] = zone_soils
    ctx.state["zones_by_site"] = {
        s["id"]: {k: [z["id"] for z in zones if z["site_id"] == s["id"] and z["kind"] == k] for k in s["zones"]}
        for s in ctx.world["sites"]
    }
    ctx.state["design_surface_by_zone"] = {z["id"]: z["design_surface_id"] for z in zones if z["design_surface_id"]}
    ctx.state["chargers_by_site"] = {
        s["id"]: [c for c in chargers if c["site_id"] == s["id"]] for s in ctx.world["sites"]
    }


def _design_surface(
    rng: np.random.Generator,
    ds_id: str,
    site_id: str,
    zone_id: str,
    cx: float,
    cy: float,
    w: float,
    h: float,
    cell: float,
) -> dict[str, Any]:
    nx, ny = max(2, int(w / cell)), max(2, int(h / cell))
    kind = str(rng.choice(["bench", "trench", "slope"]))
    base = rng.uniform(-4.0, -1.0)
    xs = np.linspace(0, 1, nx)
    if kind == "trench":
        grid = np.tile(np.where(np.abs(xs - 0.5) < 0.15, base, 0.0), (ny, 1))
    elif kind == "slope":
        grid = np.tile(base * xs, (ny, 1))
    else:
        grid = np.full((ny, nx), base)
    return {
        "id": ds_id,
        "site_id": site_id,
        "zone_id": zone_id,
        "kind": kind,
        "cell_m": cell,
        "origin": json.dumps([round(cx - w / 2, 1), round(cy - h / 2, 1)]),
        "grid": json.dumps(np.round(grid, 2).tolist()),
    }

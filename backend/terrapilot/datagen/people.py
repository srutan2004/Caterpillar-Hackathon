"""People (§7.3): users by role, operator profiles, latent traits (truth only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from terrapilot.core.security import hash_pin
from terrapilot.datagen.context import GenContext


@dataclass
class OperatorRt:
    id: str
    name: str
    site_id: str
    classes: list[str]
    experience_years: float
    skill: float
    idle_propensity: float
    belt_compliance_p: float
    aggression: float
    fatigue_susceptibility: float


def _sigmoid(x: float) -> float:
    return float(1 / (1 + np.exp(-x)))


def generate_people(ctx: GenContext) -> None:
    rng = ctx.rng("people")
    ocfg = ctx.dg["operators"]
    fixtures = (ctx.dg.get("demo_fixtures") or {}).get("operators", {})
    names = ocfg["names"]
    iterations = int(ctx.cfg.app.auth.pin_hash["iterations"])
    pin = str(ocfg["auth"]["demo_pin"])
    locale = ocfg["locale_default"]
    fmt = ocfg["id_formats"]

    machines = ctx.state["machine_plan"]  # [(machine_id, manifest_id, class, site)]
    site_weights: dict[str, int] = {}
    classes_at_site: dict[str, list[str]] = {}
    for _, _, cls, site in machines:
        site_weights[site] = site_weights.get(site, 0) + 1
        classes_at_site.setdefault(site, []).append(cls)

    def person_name() -> str:
        return f"{rng.choice(names['given'])} {rng.choice(names['family'])}"

    users: list[dict[str, Any]] = []
    badge = iter(range(10001, 99999))

    def add_user(uid: str, role: str, site: str | None) -> None:
        salt = rng.bytes(16)
        users.append(
            {
                "id": uid,
                "name": person_name(),
                "role": role,
                "locale": locale,
                "pin_hash": hash_pin(pin, iterations, salt),
                "badge_id": f"B{next(badge)}",
                "site_id": site,
            }
        )

    sites = sorted(site_weights)
    w = np.array([site_weights[s] for s in sites], dtype=float)
    operators: dict[str, OperatorRt] = {}
    tr = ocfg["traits"]
    n_ops = int(ctx.world["operators"]["count"])
    exp_cfg = ctx.world["operators"]["experience_years"]
    for n in range(1, n_ops + 1):
        oid = fmt["operator"].format(n=n)
        pin_fx = fixtures.get(oid, {})
        site = pin_fx.get("site") or str(rng.choice(sites, p=w / w.sum()))
        avail = sorted(set(classes_at_site.get(site, [])))
        k = int(
            rng.integers(
                ocfg["certified_classes_per_operator"]["min"], ocfg["certified_classes_per_operator"]["max"] + 1
            )
        )
        classes = pin_fx.get("classes") or [str(c) for c in rng.choice(avail, size=min(k, len(avail)), replace=False)]
        exp = float(rng.lognormal(exp_cfg["mu"], exp_cfg["sigma"]))
        traits = {
            "skill": _sigmoid(
                tr["skill"]["from_experience"]["a"]
                + tr["skill"]["from_experience"]["b"] * np.log1p(exp)
                + rng.normal(0, tr["skill"]["noise_sd"])
            ),
            "idle_propensity": float(rng.beta(*tr["idle_propensity"]["beta"])),
            "belt_compliance_p": float(rng.beta(*tr["belt_compliance_p"]["beta"])),
            "aggression": float(rng.beta(*tr["aggression"]["beta"])),
            "fatigue_susceptibility": float(rng.beta(*tr["fatigue_susceptibility"]["beta"])),
        } | pin_fx.get("traits", {})
        add_user(oid, "operator", site)
        operators[oid] = OperatorRt(
            id=oid,
            name=users[-1]["name"],
            site_id=site,
            classes=classes,
            experience_years=round(exp, 2),
            **{k: round(float(v), 4) for k, v in traits.items()},
        )

    # primary operator per machine: pinned pairs first, then an unpaired certified operator on the site,
    # otherwise an unpaired operator on the site is certified for that class
    pinned = {
        t["machine"]: t["operator"]
        for t in (ctx.dg.get("demo_fixtures") or {}).get("today_tasks", [])
        if t.get("machine") and t.get("operator")
    }
    primary: dict[str, str] = {}
    taken: set[str] = set()
    for mid, _, _cls, _site in machines:
        if mid in pinned and pinned[mid] in operators:
            primary[mid] = pinned[mid]
            taken.add(pinned[mid])
    for mid, _, cls, site in machines:
        if mid in primary:
            continue
        pool = [o for o in operators.values() if o.site_id == site and o.id not in taken]
        certified = [o for o in pool if cls in o.classes]
        chosen = certified[0] if certified else (pool[0] if pool else None)
        if chosen is None:
            chosen = next(o for o in operators.values() if o.id not in taken)
            chosen.site_id = site
        if cls not in chosen.classes:
            chosen.classes.append(cls)
        primary[mid] = chosen.id
        taken.add(chosen.id)
    ctx.state["primary_operator"] = primary

    for n in range(1, int(ctx.world["instructors"]["count"]) + 1):
        add_user(fmt["instructor"].format(n=n), "instructor", sites[(n - 1) % len(sites)])
    for s in ctx.world["sites"]:
        for _ in range(int(ctx.world["supervisors"]["per_site"])):
            add_user(fmt["supervisor"].format(site=s["id"].removeprefix("site_")), "supervisor", s["id"])
    technicians: dict[str, float] = {}
    t_exp = ctx.world["technicians"]["experience_years"]
    for n in range(1, int(ctx.world["technicians"]["count"]) + 1):
        tid = fmt["technician"].format(n=n)
        add_user(tid, "technician", sites[(n - 1) % len(sites)])
        technicians[tid] = round(float(rng.lognormal(t_exp["mu"], t_exp["sigma"])), 2)
    for n in range(1, int(ctx.world["admins"]["count"]) + 1):
        add_user(fmt["admin"].format(n=n), "admin", None)

    for u in users:
        if u["id"] in operators:
            u["site_id"] = operators[u["id"]].site_id
    ctx.emit("users", pd.DataFrame(users))
    ctx.emit(
        "operator_profiles",
        pd.DataFrame(
            [
                {
                    "user_id": o.id,
                    "experience_years": o.experience_years,
                    "home_site_id": o.site_id,
                    "certified_classes": o.classes,
                }
                for o in operators.values()
            ]
        ),
    )
    ctx.emit(
        "truth_operator_traits",
        pd.DataFrame(
            [
                {
                    "operator_id": o.id,
                    "skill": o.skill,
                    "idle_propensity": o.idle_propensity,
                    "belt_compliance_p": o.belt_compliance_p,
                    "aggression": o.aggression,
                    "fatigue_susceptibility": o.fatigue_susceptibility,
                }
                for o in operators.values()
            ]
        ),
    )
    ctx.state["operators"] = operators
    ctx.state["technicians"] = technicians

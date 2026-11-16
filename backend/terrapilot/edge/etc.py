"""Live ETC (§10.6): Bayesian blend of the observed production rate with the model's prior rate.

    rate_live = (n·rate_obs + k·rate_model) / (n + k)     n = completed cycles, k = prior strength (config)
    ETC       = now + remaining_qty / rate_live

The interval combines the model's (conformalised) log-width, shrinking as cycles accrue, with the observed
cycle-time dispersion. Pure maths: the edge runs it with a prior that the cloud computed before the shift.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class TaskPrior:
    rate_per_min: float  # model p50 quantity per minute
    log_half_width: float  # (ln p90 − ln p10) / 2 of the model duration
    source: str = "plan"  # model | plan


@dataclass(frozen=True)
class LiveEtc:
    rate_live: float
    remaining_min_p50: float
    remaining_min_p10: float
    remaining_min_p90: float
    etc_p50: datetime
    etc_p10: datetime
    etc_p90: datetime
    weight_observed: float


def blend_rate(n: float, rate_obs: float, rate_model: float, k: float) -> float:
    if n <= 0 or rate_obs <= 0:
        return rate_model
    return (n * rate_obs + k * rate_model) / (n + k)


def live_etc(
    now: datetime,
    remaining_qty: float,
    n_cycles: float,
    rate_obs: float,
    prior: TaskPrior,
    k: float,
    cycle_cv: float,
    z: float,
) -> LiveEtc:
    rate = max(blend_rate(n_cycles, rate_obs, prior.rate_per_min, k), 1e-9)
    w_obs = n_cycles / (n_cycles + k) if n_cycles > 0 else 0.0
    obs_hw = z * cycle_cv / math.sqrt(max(n_cycles, 1.0))
    hw = math.hypot((1 - w_obs) * prior.log_half_width, w_obs * obs_hw)
    mid = max(remaining_qty, 0.0) / rate
    lo, hi = mid * math.exp(-hw), mid * math.exp(hw)
    return LiveEtc(
        rate_live=rate,
        remaining_min_p50=mid,
        remaining_min_p10=lo,
        remaining_min_p90=hi,
        etc_p50=now + timedelta(minutes=mid),
        etc_p10=now + timedelta(minutes=lo),
        etc_p90=now + timedelta(minutes=hi),
        weight_observed=w_obs,
    )


def prior_from_plan(quantity: float, planned_min: float, log_half_width: float) -> TaskPrior:
    return TaskPrior(quantity / max(planned_min, 1e-6), log_half_width, "plan")

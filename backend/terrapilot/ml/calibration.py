"""Conformal wrappers and interval metrics (§11): CQR, PICP, pinball loss, ECE."""

from __future__ import annotations

import itertools
import math

import numpy as np


def cqr_offset(y: np.ndarray, lo: np.ndarray, hi: np.ndarray, alpha: float) -> float:
    """Conformalized Quantile Regression (Romano et al. 2019): the finite-sample correction Q such that
    [lo − Q, hi + Q] covers ≥ 1 − alpha on exchangeable data."""
    scores = np.maximum(lo - y, y - hi)
    n = len(scores)
    if n == 0:
        return 0.0
    level = min(1.0, math.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def picp(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    return float(np.mean((y >= lo) & (y <= hi))) if len(y) else math.nan


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def mape(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(p - y) / np.maximum(np.abs(y), 1e-9)))


def ece(prob: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for a, b in itertools.pairwise(edges):
        m = (prob >= a) & (prob < b if b < 1 else prob <= b)
        if m.any():
            total += m.mean() * abs(prob[m].mean() - correct[m].mean())
    return float(total)

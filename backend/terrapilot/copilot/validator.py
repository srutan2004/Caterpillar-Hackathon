"""Output validator (§12.1 step 4, §13.1 output layer): an LLM sentence may only restate the facts.

* every number in the text must match a fact value (after rounding to the precision the text uses);
* direction words must agree with `facts.direction`;
* no banned phrase; at most `max_words` words.
Shared by the live narrator and the maintenance/plan explainers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUM = re.compile(r"(?<![\w.])[-−]?\d+(?:[.,]\d+)?")
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
_UNITS = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_TENS = {
    w: 10 * (i + 2)
    for i, w in enumerate(["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"])
}
_WORDNUM = re.compile(
    r"\b(?:(" + "|".join(_TENS) + r")(?:[- ](" + "|".join(list(_UNITS)[1:10]) + r"))?|(" + "|".join(_UNITS) + r"))\b"
    r"(?:\s+hundred\b)?",
    re.IGNORECASE,
)


def word_numbers(text: str) -> list[float]:
    """Numbers spelled out in words ("sixty-five", "four"): the model may not smuggle numbers past the check."""
    out = []
    for m in _WORDNUM.finditer(text):
        tens, unit, single = (g.lower() if g else None for g in m.groups())
        value = _TENS[tens] + (_UNITS[unit] if unit else 0) if tens else _UNITS[single or "zero"]
        if m.group(0).lower().endswith("hundred"):
            value *= 100
        out.append(float(value))
    return out


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def fact_numbers(facts: Any) -> list[float]:
    out: list[float] = []
    if isinstance(facts, dict):
        for v in facts.values():
            out += fact_numbers(v)
    elif isinstance(facts, list | tuple):
        for v in facts:
            out += fact_numbers(v)
    elif isinstance(facts, bool):
        return out
    elif isinstance(facts, int | float):
        out.append(float(facts))
    elif isinstance(facts, str):
        out += [float(m.replace("−", "-").replace(",", ".")) for m in _NUM.findall(_TIME.sub(" ", facts))]
    return out


def fact_strings(facts: Any) -> list[str]:
    if isinstance(facts, dict):
        return [s for v in facts.values() for s in fact_strings(v)]
    if isinstance(facts, list | tuple):
        return [s for v in facts for s in fact_strings(v)]
    return [facts] if isinstance(facts, str) else []


def _matches(n: float, values: list[float], decimals: int, tol: float) -> bool:
    for v in values:
        for cand in (v, abs(v)):
            if abs(round(cand, decimals) - n) <= tol or abs(cand - n) <= tol:
                return True
    return False


def validate(text: str, facts: dict[str, Any], cfg: dict[str, Any], max_words: int | None = None) -> Verdict:
    reasons: list[str] = []
    low = text.lower()
    tol = float(cfg.get("number_tolerance", 0.051))
    values = fact_numbers(facts)
    allowed_times = {t for s in fact_strings(facts) for t in _TIME.findall(s)}
    for t in _TIME.findall(text):
        if t not in allowed_times:
            reasons.append(f"time {t} not in facts")
    for raw in _NUM.findall(_TIME.sub(" ", text)):
        n = float(raw.replace("−", "-").replace(",", "."))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if not _matches(abs(n), values, decimals, tol):
            reasons.append(f"number {raw} not in facts")
    for n in word_numbers(text):
        if not _matches(n, values, 0, tol):
            reasons.append(f"number word {n:g} not in facts")
    for phrase in cfg.get("banned_phrases", []):
        if phrase.lower() in low:
            reasons.append(f"banned phrase '{phrase}'")
    direction = facts.get("direction") if isinstance(facts, dict) else None
    words = cfg.get("direction_words", {})
    if direction in words:
        own = [w for w in words[direction]]
        others = [w for d, ws in words.items() if d != direction for w in ws]
        if not any(re.search(rf"\b{re.escape(w)}\b", low) for w in own):
            reasons.append(f"direction '{direction}' not stated")
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in others):
            reasons.append("contradicting direction word")
    if max_words is not None and len(text.split()) > max_words:
        reasons.append("too long")
    return Verdict(not reasons, reasons)

"""Numeric grounding for generated manuals: every unit-bearing number must come from the SPEC VALUES."""

from __future__ import annotations

import json
import re
from typing import Any

UNIT = r"(?:mm|cm|m|km|kph|km/h|m/s|bar|kPa|°C|degC|%|t|kg|L|l|h|min|s|kW|kWh|V|mV|kohm|ppm|deg|°|rpm|m³|m3)"
# thousands separators (1,000 / 1 000 / 1 000) are part of the number, not a boundary
NUM_UNIT = re.compile(r"(?<![\w.,])(\d{1,3}(?:[,   ]\d{3})+|\d+(?:\.\d+)?)[\s  ]?" + UNIT + r"(?![\w])")
NUM = re.compile(r"(?<![\w.])\d{1,3}(?:[,  ]\d{3})+|(?<![\w.])\d+(?:\.\d+)?")


def _value(raw: str) -> float:
    return float(re.sub(r"[,   ]", "", raw))


def allowed_numbers(variables: dict[str, Any]) -> set[float]:
    return {_value(x) for x in NUM.findall(json.dumps(variables, ensure_ascii=False))}


def unsupported(text: str, variables: dict[str, Any]) -> list[str]:
    """Unit-bearing numbers in `text` that are not in the SPEC VALUES the section was generated from."""
    ok = allowed_numbers(variables)
    return sorted({m.group(0) for m in NUM_UNIT.finditer(text) if _value(m.group(1)) not in ok})

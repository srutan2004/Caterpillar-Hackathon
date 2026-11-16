"""Cab notes (§7.3 Voice/notes): templated notes; LLM paraphrases are added by `tp content --task notes`."""

from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from terrapilot.core.settings import REPO_ROOT
from terrapilot.datagen.context import GenContext


def generate_notes(ctx: GenContext) -> None:
    cfg = ctx.dg["notes"]
    rng = ctx.rng("notes")
    tags = list(cfg["tag_weights"])
    w = np.array(list(cfg["tag_weights"].values()), dtype=float)
    primary = {v: k for k, v in ctx.state["primary_operator"].items()}
    rows = []
    weeks = ctx.history_days / 7
    paraphrases = _approved_paraphrases()
    for op in ctx.state["operators"].values():
        machine = primary.get(op.id)
        zones = ctx.state["zones_by_site"][op.site_id]["dig"]
        for i in range(int(rng.poisson(cfg["per_operator_per_week"] * weeks))):
            tag = str(rng.choice(tags, p=w / w.sum()))
            template = str(rng.choice(cfg["templates"][tag]))
            text = template.format(zone=str(rng.choice(zones)))
            if text in paraphrases and rng.random() < 0.5:
                text = str(rng.choice(paraphrases[text]))
            day = ctx.first_day + timedelta(days=int(rng.integers(0, ctx.history_days)))
            rows.append(
                {
                    "id": f"CN-{op.id}-{i}",
                    "operator_id": op.id,
                    "machine_id": machine,
                    "ts": ctx.shift_start(day) + timedelta(minutes=float(rng.uniform(20, 580))),
                    "text": text,
                    "audio_uri": None,
                    "tags": [tag],
                }
            )
    ctx.emit("cab_notes", pd.DataFrame(rows))


def _approved_paraphrases() -> dict[str, list[str]]:
    path = REPO_ROOT / "knowledge" / "notes" / "paraphrases.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["source"]: item["variants"] for item in data.get("notes", [])}

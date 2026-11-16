"""Structured knowledge tables (§7.7): fault-code catalogue and parts catalogue, straight from config."""

from __future__ import annotations

import json

import pandas as pd

from terrapilot.datagen.context import GenContext


def generate_knowledge(ctx: GenContext) -> None:
    ctx.emit(
        "fault_codes",
        pd.DataFrame(
            [
                {
                    "code": f.code,
                    "component": f.component,
                    "severity": f.severity,
                    "classes": f.classes,
                    "title_key": f.title_key,
                    "description": f.description,
                    "probable_causes": f.probable_causes,
                    "checks": f.checks,
                    "safe_to_continue": f.safe_to_continue,
                    "manual_ref": json.dumps(f.manual_ref),
                    "part_numbers": f.part_numbers,
                }
                for f in ctx.cfg.fault_catalogue
            ]
        ),
    )
    ctx.emit("parts", pd.DataFrame([p.model_dump() for p in ctx.cfg.parts]))

"""Build content-generation requests from config: manual outlines + manifest spec values, quiz sources,
cab-note templates. Numbers in manuals come only from the manifests, so text and config stay consistent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from terrapilot.core.config import ConfigBundle, flatten_keys
from terrapilot.core.refs import RefError, get_path
from terrapilot.core.settings import REPO_ROOT


@dataclass
class ContentRequest:
    custom_id: str
    task: str  # manuals | quizzes | notes
    prompt: str
    variables: dict[str, Any]
    meta: dict[str, Any]


def safe_id(custom_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", custom_id)


def _spec_values(cfg: ConfigBundle, manifest_ids: list[str], paths: list[str]) -> str:
    out: dict[str, Any] = {}
    for mid in manifest_ids:
        doc = cfg.manifests_raw[mid]
        values: dict[str, Any] = {}
        for p in paths:
            if p == "service_intervals_ref":
                values["service_intervals"] = cfg.service_intervals.get(mid, [])
                continue
            try:
                values[p] = get_path(doc, p)
            except RefError:
                continue
        out[mid] = values
    return yaml.safe_dump(out, sort_keys=False, allow_unicode=True)


def _t(cfg: ConfigBundle, key: str) -> str:
    return str(flatten_keys(cfg.i18n[cfg.app.locales.default]).get(key, key))


def manual_requests(cfg: ConfigBundle, machine_class: str | None = None) -> list[ContentRequest]:
    outline = cfg.datagen["manual_outline"]
    sub = cfg.llm.tasks["content_gen"].subtasks["manuals"]  # type: ignore[index]
    out: list[ContentRequest] = []
    for cls, spec in outline["classes"].items():
        if machine_class and cls != machine_class:
            continue
        for section in outline["sections"]:
            proc = section.get("procedure_ids")
            if proc == "auto_from_fault_catalogue":
                proc = [f.code for f in cfg.fault_catalogue if cls in f.classes]
            sect = {**section, "procedure_ids": proc or []}
            out.append(
                ContentRequest(
                    custom_id=f"manuals:{cls}:{section['id']}",
                    task="manuals",
                    prompt=sub["prompt"],
                    variables={
                        "machine_name": _t(cfg, spec["machine_name_key"]),
                        "section": sect,
                        "target_words": sub["target_words"],
                        "spec_values": _spec_values(cfg, spec["manifests"], section.get("spec_paths", [])),
                    },
                    meta={
                        "machine_class": cls,
                        "section": section["id"],
                        "procedure_ids": proc or [],
                        "manifests": spec["manifests"],
                    },
                )
            )
    if machine_class in (None, "common"):
        for section in outline.get("common_sections", []):
            out.append(
                ContentRequest(
                    custom_id=f"manuals:common:{section['id']}",
                    task="manuals",
                    prompt=sub["prompt"],
                    variables={
                        "machine_name": "heavy equipment (all machines)",
                        "section": {**section, "procedure_ids": []},
                        "target_words": sub["target_words"],
                        "spec_values": "{}",
                    },
                    meta={"machine_class": "common", "section": section["id"], "procedure_ids": [], "manifests": []},
                )
            )
    return out


def split_chunks(markdown: str) -> list[tuple[str, str]]:
    """Structure-aware chunks: each '### PROCEDURE' block or '## ' section is one chunk."""
    body = re.sub(r"^---.*?---\s*", "", markdown, flags=re.S)
    parts = re.split(r"(?m)^(?=### PROCEDURE|## )", body)
    chunks = []
    for part in parts:
        text = part.strip()
        if len(text) < 80:
            continue
        title = text.splitlines()[0].lstrip("# ").strip()
        chunks.append((title, text))
    return chunks


def quiz_requests(cfg: ConfigBundle, knowledge_dir: Path | None = None) -> list[ContentRequest]:
    base = knowledge_dir or REPO_ROOT / "knowledge" / "manuals"
    sources = cfg.datagen["training"].get("quiz_sources", {})
    sub = cfg.llm.tasks["content_gen"].subtasks["quizzes"]  # type: ignore[index]
    out: list[ContentRequest] = []
    for module, refs in sources.items():
        for ref in refs:
            path = base / f"{ref}.md"
            if not path.is_file():
                continue
            for i, (title, text) in enumerate(split_chunks(path.read_text(encoding="utf-8"))):
                chunk_id = f"{ref}#{i}"
                out.append(
                    ContentRequest(
                        custom_id=f"quizzes:{module}:{ref}:{i}",
                        task="quizzes",
                        prompt=sub["prompt"],
                        variables={
                            "n_questions": sub["n_questions"],
                            "module_id": module,
                            "chunk_id": chunk_id,
                            "chunk_text": text,
                        },
                        meta={"module_id": module, "source_chunk_id": chunk_id, "chunk_title": title},
                    )
                )
    return out


def notes_requests(cfg: ConfigBundle) -> list[ContentRequest]:
    ncfg = cfg.datagen["notes"]
    sub = cfg.llm.tasks["content_gen"].subtasks["notes"]  # type: ignore[index]
    notes = [
        {"source_id": f"{tag}:{i}", "text": t}
        for tag, templates in ncfg["templates"].items()
        for i, t in enumerate(templates)
    ]
    return [
        ContentRequest(
            custom_id="notes:all",
            task="notes",
            prompt=sub["prompt"],
            variables={"n_variants": sub["n_variants"], "notes": notes},
            meta={"sources": notes},
        )
    ]


def build_requests(cfg: ConfigBundle, task: str, machine_class: str | None = None) -> list[ContentRequest]:
    if task == "manuals":
        return manual_requests(cfg, machine_class)
    if task == "quizzes":
        return quiz_requests(cfg)
    if task == "notes":
        return notes_requests(cfg)
    raise ValueError(f"unknown content task '{task}' (manuals | quizzes | notes)")

"""Human review queue (§7.7): nothing generated reaches knowledge/ (and therefore RAG or quizzes) unreviewed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from terrapilot.content.jobs import queue_dir
from terrapilot.core.settings import REPO_ROOT
from terrapilot.core.timeutil import utcnow

KNOWLEDGE = REPO_ROOT / "knowledge"


def _items() -> list[tuple[Path, dict[str, Any]]]:
    base = queue_dir()
    out = []
    for path in sorted(base.glob("*/*.json")):
        if path.parent.name.startswith("_"):
            continue
        out.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return out


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def approve_item(item: dict[str, Any]) -> Path:
    task, meta, content = item["task"], item.get("meta", {}), _strip_fences(item["content"])
    stamp = utcnow().isoformat()
    if task == "manuals":
        target: Path = KNOWLEDGE / "manuals" / meta["machine_class"] / f"{meta['section']}.md"
        front = {
            "machine_class": meta["machine_class"],
            "section": meta["section"],
            "procedure_ids": meta.get("procedure_ids", []),
            "source": f"generated:{item.get('model', '')}",
            "reviewed_at": stamp,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n" + content + "\n", encoding="utf-8"
        )
        return target
    if task == "quizzes":
        data = json.loads(content)
        target = KNOWLEDGE / "quizzes" / f"{item['id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "module_id": meta["module_id"],
                    "source_chunk_id": meta["source_chunk_id"],
                    "reviewed_at": stamp,
                    "questions": data.get("questions", []),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return target
    if task == "notes":
        data = json.loads(content)
        sources = {s["source_id"]: s["text"] for s in meta.get("sources", [])}
        target = KNOWLEDGE / "notes" / "paraphrases.json"
        existing = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {"notes": []}
        by_source = {n["source"]: n for n in existing["notes"]}
        for n in data.get("notes", []):
            src = sources.get(n.get("source_id"))
            if src:
                by_source[src] = {"source": src, "variants": n.get("variants", [])}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"reviewed_at": stamp, "notes": list(by_source.values())}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target
    raise ValueError(f"unknown task '{task}'")


def review_cli(action: str, item_id: str | None, console: Console) -> None:
    items = _items()
    if action == "list":
        table = Table("id", "task", "status", "model", "created")
        for _, it in items:
            table.add_row(it["id"], it["task"], it["status"], it.get("model", ""), it["created_at"][:19])
        console.print(table if items else "review queue is empty")
        return
    targets = [
        (p, it) for p, it in items if item_id in (it["id"], "all") and (item_id != "all" or it["status"] == "pending")
    ]
    if not targets:
        console.print(f"[red]no review item '{item_id}'[/red]")
        return
    for path, it in targets:
        if action == "show":
            console.print(it["content"])
        elif action == "approve":
            written = approve_item(it)
            it["status"], it["reviewed_at"] = "approved", utcnow().isoformat()
            path.write_text(json.dumps(it, indent=2, ensure_ascii=False), encoding="utf-8")
            console.print(f"[green]✓ approved {it['id']}[/green] → {written.relative_to(REPO_ROOT)}")
        elif action == "reject":
            it["status"], it["reviewed_at"] = "rejected", utcnow().isoformat()
            path.write_text(json.dumps(it, indent=2, ensure_ascii=False), encoding="utf-8")
            console.print(f"rejected {it['id']}")
        else:
            console.print(f"[red]unknown action '{action}'[/red]")
            return

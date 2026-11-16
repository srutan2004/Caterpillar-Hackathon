"""`tp content` / `tp content-status`: submit content requests to Groq and collect results for review.

* batch   — Groq Batch API (JSONL upload → batch → poll → download), cheapest for bulk content
* sync    — direct calls through the LLM gateway (rate-limited, with fallbacks)
* dry-run — only writes the JSONL so the prompts can be inspected without an API key
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from terrapilot.content.requests import ContentRequest, build_requests, safe_id
from terrapilot.core.config import get_config
from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import utcnow
from terrapilot.llm.prompts import PromptRegistry


def queue_dir() -> Path:
    cfg = get_config()
    return get_settings().data_dir / str(cfg.llm.content["review_queue_dir"])


def _batches_file() -> Path:
    return queue_dir() / "_batches" / "batches.json"


def _load_batches() -> list[dict[str, Any]]:
    path = _batches_file()
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _save_batches(batches: list[dict[str, Any]]) -> None:
    path = _batches_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(batches, indent=2), encoding="utf-8")


def _body(req: ContentRequest, prompts: PromptRegistry) -> dict[str, Any]:
    cfg = get_config()
    task = cfg.llm.tasks["content_gen"]
    sub = (task.subtasks or {})[req.task]
    body: dict[str, Any] = {
        "model": task.model,
        "messages": prompts.render(req.prompt, req.variables),
        "temperature": task.temperature,
        "max_completion_tokens": task.max_tokens,
        **task.params,
    }
    if sub.get("response_format", {}).get("type") == "json_object":
        body["response_format"] = {"type": "json_object"}
    return body


def write_review_item(
    req_meta: dict[str, Any], custom_id: str, task: str, content: str, model: str, source: str
) -> Path:
    path = queue_dir() / task / f"{safe_id(custom_id)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    item = {
        "id": safe_id(custom_id),
        "custom_id": custom_id,
        "task": task,
        "status": "pending",
        "model": model,
        "source": source,
        "created_at": utcnow().isoformat(),
        "meta": req_meta,
        "content": content,
    }
    path.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def submit_content(task: str, mode: str, machine_class: str | None, limit: int | None, console: Console) -> None:
    cfg = get_config()
    prompts = PromptRegistry(cfg.root)
    requests = build_requests(cfg, task, machine_class)
    if limit:
        requests = requests[:limit]
    if not requests:
        hint = " (approve some manuals first: `tp review approve all`)" if task == "quizzes" else ""
        console.print(f"[yellow]no {task} requests to submit{hint}[/yellow]")
        return
    stamp = utcnow().strftime("%Y%m%dT%H%M%S")
    jsonl = queue_dir() / "_batches" / f"{stamp}_{task}.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    meta = {r.custom_id: r.meta for r in requests}
    with jsonl.open("w", encoding="utf-8") as fh:
        for r in requests:
            fh.write(
                json.dumps(
                    {
                        "custom_id": r.custom_id,
                        "method": "POST",
                        "url": "/v1/chat/completions",
                        "body": _body(r, prompts),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    console.print(f"wrote {len(requests)} requests → {jsonl}")
    if mode == "dry-run":
        return
    if mode == "batch":
        import groq

        from terrapilot.llm.providers.groq_provider import GroqProvider

        provider = GroqProvider(get_settings().groq_key, cfg.llm.providers["groq"].model_dump().get("base_url"))
        try:
            file_id = provider.upload_batch_file(jsonl)
            batch = provider.create_batch(file_id, cfg.llm.content["batch_completion_window"], {"task": task})
        except groq.PermissionDeniedError:
            console.print(
                "[yellow]Groq Batch API is not available on this plan — using rate-limited sync calls.[/yellow]"
            )
            mode = "sync"
    if mode == "batch":
        batches = _load_batches()
        batches.append(
            {
                "batch_id": batch["id"],
                "task": task,
                "status": batch.get("status"),
                "input_file": str(jsonl),
                "submitted_at": utcnow().isoformat(),
                "meta": meta,
                "requests": len(requests),
            }
        )
        _save_batches(batches)
        console.print(f"[green]✓ submitted Groq batch {batch['id']}[/green] — check with `uv run tp content-status`")
        return
    if mode == "sync":
        from terrapilot.llm.gateway import LLMUnavailableError, get_gateway

        gw = get_gateway()
        ok = 0
        for r in requests:
            try:
                res = gw.run(
                    "content_gen",
                    r.variables,
                    prompt_override=r.prompt,
                    extra_params={"response_format": {"type": "json_object"}} if r.task != "manuals" else None,
                )
            except LLMUnavailableError as exc:
                console.print(f"[red]✗ {r.custom_id}: {exc}[/red]")
                continue
            text, remaining = _numeric_revise(gw, r, res.text, console)
            item_meta: dict[str, Any] = (
                {**r.meta, "unsupported_numbers": remaining} if remaining is not None else dict(r.meta)
            )
            write_review_item(item_meta, r.custom_id, r.task, text, res.model, "sync")
            ok += 1
            flag = "" if not remaining else f" — {len(remaining)} unsupported numbers remain"
            console.print(f"  • {r.custom_id} ({res.model}, {res.latency_ms:.0f} ms){flag}")
        console.print(f"[green]✓ {ok}/{len(requests)} items in the review queue[/green] — `uv run tp review list`")
        return
    raise ValueError(f"unknown mode '{mode}' (batch | sync | dry-run)")


def _numeric_revise(gw: Any, req: ContentRequest, text: str, console: Console) -> tuple[str, list[str] | None]:
    """Manuals: re-ask with the offending numbers until every number is grounded in SPEC VALUES (§7.7)."""
    from terrapilot.content.numbers import unsupported
    from terrapilot.llm.gateway import LLMUnavailableError

    sub = (get_config().llm.tasks["content_gen"].subtasks or {}).get(req.task, {})
    nc = sub.get("numeric_check")
    if not nc:
        return text, None
    bad = unsupported(text, req.variables)
    for _ in range(int(nc["max_revisions"])):
        if not bad:
            break
        try:
            res = gw.run(
                "content_gen",
                {"unsupported": bad, "spec_values": req.variables.get("spec_values", ""), "text": text},
                prompt_override=nc["revise_prompt"],
            )
        except LLMUnavailableError as exc:
            console.print(f"[yellow]revision failed: {exc}[/yellow]")
            break
        text = res.text
        bad = unsupported(text, req.variables)
    return text, bad


def poll_batches(fetch: bool, console: Console) -> None:
    cfg = get_config()
    batches = _load_batches()
    if not batches:
        console.print("no submitted batches")
        return
    from terrapilot.llm.providers.groq_provider import GroqProvider

    provider = GroqProvider(get_settings().groq_key, cfg.llm.providers["groq"].model_dump().get("base_url"))
    table = Table("batch", "task", "status", "requests", "collected")
    for b in batches:
        if b.get("collected"):
            table.add_row(b["batch_id"], b["task"], b["status"], str(b["requests"]), "yes")
            continue
        info = provider.get_batch(b["batch_id"])
        b["status"] = info.get("status")
        if fetch and info.get("status") == "completed" and info.get("output_file_id"):
            n = 0
            for line in provider.download_file(info["output_file_id"]).splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                body = (rec.get("response") or {}).get("body") or {}
                choices = body.get("choices") or []
                if not choices:
                    continue
                cid = rec["custom_id"]
                write_review_item(
                    b["meta"].get(cid, {}),
                    cid,
                    b["task"],
                    choices[0]["message"]["content"],
                    body.get("model", ""),
                    "batch",
                )
                n += 1
            b["collected"] = True
            b["collected_items"] = n
        table.add_row(b["batch_id"], b["task"], str(b["status"]), str(b["requests"]), str(b.get("collected_items", "")))
    _save_batches(batches)
    console.print(table)

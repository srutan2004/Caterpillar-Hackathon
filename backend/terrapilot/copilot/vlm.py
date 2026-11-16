"""Visual troubleshooting (§10.7.3): photo → closed-label VLM → manual grounding → escalation guard.

Confidence is self-consistency (agreement across `samples` runs), never the model's own claim. `safe_to_continue`
always comes from the fault catalogue, never from the VLM (§13.1 decision authority).
"""

from __future__ import annotations

import base64
from collections import Counter
from pathlib import Path
from typing import Any

from terrapilot.copilot.guard_log import guard_row
from terrapilot.copilot.guards import RuntimeRules
from terrapilot.core.config import ConfigBundle
from terrapilot.core.logging import get_logger

log = get_logger("copilot.vlm")
UNKNOWN = "unknown"
JPEG_QUALITY = 85
SAFETY_RELEVANT = ("no", "limited")  # catalogue safe_to_continue values that make a label safety relevant


def label_set(cfg: ConfigBundle, machine_class: str) -> list[str]:
    codes = [f.code for f in cfg.fault_catalogue if machine_class in f.classes]
    return [*codes, UNKNOWN]


def _image_data_url(path: Path, max_px: int) -> str:
    """Downscale and strip metadata before anything leaves the machine (§12.3 privacy)."""
    from io import BytesIO

    from PIL import Image

    with Image.open(path) as src:
        rgb = src.convert("RGB")
    rgb.thumbnail((max_px, max_px))
    buf = BytesIO()
    rgb.save(buf, format="JPEG", quality=JPEG_QUALITY)  # re-encode drops EXIF
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def diagnose(
    cfg: ConfigBundle, image: Path, manifest_id: str, machine_id: str, note: str, gateway: Any = None
) -> dict[str, Any]:
    manifest = cfg.manifests_raw[manifest_id]
    machine_class = str(manifest["class"])
    labels = label_set(cfg, machine_class)
    components = sorted({f.component for f in cfg.fault_catalogue if machine_class in f.classes})
    task = cfg.llm.tasks["vlm_troubleshoot"]
    samples: list[dict[str, Any]] = []
    guard_events: list[dict[str, Any]] = []
    if gateway is not None:
        image_url = _image_data_url(image, int(task.max_image_px or 1280))
        for _ in range(int(task.samples or 1)):
            try:
                res = gateway.run(
                    "vlm_troubleshoot",
                    {"labels": labels, "components": components, "machine_class": machine_class, "note": note},
                    images=[image_url],
                )
                if res.provider in ("template", "sentinel"):
                    break
                out = res.output or {}
                if out.get("label") in labels:
                    samples.append(out)
            except Exception as exc:
                log.warning("vlm sample failed", error=str(exc)[:200])
                break
    counts = Counter(s["label"] for s in samples)
    label, agree = counts.most_common(1)[0] if counts else (UNKNOWN, 0)
    confidence = agree / len(samples) if samples else 0.0
    entry = cfg.fault(label) if label != UNKNOWN else None
    safety_relevant = bool(entry and entry.safe_to_continue in SAFETY_RELEVANT)
    decision = RuntimeRules(cfg).evaluate("vlm", {"confidence": confidence, "safety_relevant": safety_relevant})
    chunks: list[dict[str, Any]] = []
    if entry is not None:
        try:
            from terrapilot.copilot.knowledge import KnowledgeBase

            kb = KnowledgeBase.load(cfg)
            pid = entry.manual_ref.get("procedure_id", "")
            chunks = [{"chunk_id": c.id, "heading": c.heading, "text": c.text[:1200]} for c in kb.by_procedure(pid)]
            if not chunks:
                chunks = [
                    {"chunk_id": h.chunk.id, "heading": h.chunk.heading, "text": h.chunk.text[:1200]}
                    for h in kb.search(entry.description, [machine_class, "common"], 2)
                ]
        except (FileNotFoundError, RuntimeError):
            chunks = []
    escalate = decision.action == "escalate" or label == UNKNOWN
    if escalate:
        guard_events.append(
            guard_row(
                "runtime",
                decision.rule_id or "VLM_UNKNOWN",
                "escalate",
                {
                    "label": label,
                    "confidence": round(confidence, 2),
                    "machine_id": machine_id,
                    "safety_relevant": safety_relevant,
                },
            )
        )
    return {
        "machine_id": machine_id,
        "label": label,
        "component": entry.component if entry else (samples[0].get("component") if samples else None),
        "confidence": round(confidence, 2),
        "samples": len(samples),
        "visible_evidence": samples[0].get("visible_evidence") if samples else None,
        # the catalogue owns this decision; the VLM never sets it
        "safe_to_continue": entry.safe_to_continue if entry else None,
        "title_key": entry.title_key if entry else None,
        "checks": entry.checks if entry else [],
        "parts": entry.part_numbers if entry else [],
        "citations": chunks,
        "escalated": escalate,
        "message_key": "ask.escalate.vlm" if escalate else None,
        "guard_events": guard_events,
    }

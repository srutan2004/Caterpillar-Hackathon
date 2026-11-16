"""Guardrail layers for Ask mode (§13.1), all rules from config/guardrails/.

* input: length limits, prompt-injection (Llama Prompt Guard 2 on Groq, regex fallback), moderation
  (gpt-oss-safeguard, fail closed), topical rails (redirect legal/medical/off-topic);
* runtime: trigger → condition → action rules evaluated with safe expressions;
* output: grounding (every kept sentence cites a source), numeric consistency, banned phrases, PII scrub.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from simpleeval import EvalWithCompoundTypes

from terrapilot.copilot.validator import fact_numbers
from terrapilot.core.config import ConfigBundle
from terrapilot.core.expr import SAFE_FUNCTIONS
from terrapilot.core.logging import get_logger
from terrapilot.core.refs import load_ref_cached

log = get_logger("copilot.guards")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_NUM = re.compile(r"(?<![\w.\-/])\d+(?:\.\d+)?(?![\w/-])")
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")


@dataclass
class GuardDecision:
    action: str = "allow"  # allow | block | refuse | redirect | escalate | draft_only | bounded_fallback
    rule_id: str | None = None
    message_key: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def stops(self) -> bool:
        return self.action in ("block", "refuse", "redirect", "bounded_fallback")


# ------------------------------------------------------------------ input guard
class InputGuard:
    def __init__(self, cfg: ConfigBundle, gateway: Any = None):
        self.cfg = cfg
        self.g = cfg.guardrails["input"]
        self.gateway = gateway
        self.patterns = [re.compile(p, re.I) for p in self.g["injection"]["patterns"]]

    def injection_score(self, text: str) -> tuple[float, str]:
        """Prompt Guard 2 probability when the model is reachable, else the heuristic patterns (0 or 1)."""
        if any(p.search(text) for p in self.patterns):
            return 1.0, "heuristic"
        if self.gateway is None:
            return 0.0, "heuristic"
        try:
            from terrapilot.core.settings import get_settings
            from terrapilot.llm.providers.groq_provider import GroqProvider

            key = get_settings().groq_key
            if not key or get_settings().tp_profile == "offline":
                return 0.0, "heuristic"
            task = self.cfg.llm.tasks[self.g["injection"]["task"]]
            client = GroqProvider(key, self.cfg.llm.providers["groq"].model_dump().get("base_url")).client
            res = client.chat.completions.create(
                model=task.model,
                messages=[{"role": "user", "content": text[:2000]}],
                timeout=(task.timeout_ms or 1000) / 1000,
            )
            return float((res.choices[0].message.content or "0").strip()), "prompt_guard"
        except Exception as exc:
            log.info("prompt guard unavailable; heuristic only", error=str(exc)[:120])
            return 0.0, "heuristic"

    def moderate(self, text: str, direction: str = "input") -> GuardDecision:
        m = self.g["moderation"]
        if self.gateway is None:
            return GuardDecision()
        try:
            res = self.gateway.run(
                m["task"], {"text": text[: int(self.g["limits"]["max_chars"])], "direction": direction}
            )
        except Exception as exc:  # fail closed (config): moderation down → block
            fail = self.cfg.llm.tasks[m["task"]].fail_mode
            if fail == "closed" and self._online():
                return GuardDecision(
                    "block", "MODERATION_UNAVAILABLE", "ask.refuse.unavailable", {"error": str(exc)[:120]}
                )
            return GuardDecision()
        out = res.output or {}
        if out.get("label") in m["block_labels"] and out.get("category") in m["categories_blocked"]:
            key = "ask.refuse.override" if out.get("category") == "safety_override" else "ask.refuse.policy"
            return GuardDecision("refuse", f"MODERATION_{str(out.get('category')).upper()}", key, {"moderation": out})
        return GuardDecision(detail={"moderation": out})

    def _online(self) -> bool:
        from terrapilot.core.settings import get_settings

        return bool(get_settings().groq_key) and get_settings().tp_profile != "offline"

    def check(self, text: str, n_images: int = 0) -> GuardDecision:
        lim = self.g["limits"]
        if len(text) > int(lim["max_chars"]) or n_images > int(lim["max_images"]):
            return GuardDecision("block", "INPUT_LIMITS", "ask.refuse.too_long")
        score, source = self.injection_score(text)
        threshold = float(load_ref_cached(self.cfg.root, self.g["injection"]["threshold_ref"]))
        if score >= threshold:
            return GuardDecision(
                "block", "PROMPT_INJECTION", "ask.refuse.injection", {"score": score, "source": source}
            )
        for name, rail in self.g["topical"]["redirect"].items():
            if any(re.search(p, text, re.I) for p in rail["patterns"]):
                return GuardDecision(
                    "redirect", f"TOPICAL_{name.upper()}", rail["message_key"], {"suggested_action": rail["action"]}
                )
        return self.moderate(text)

    def sanitize_context(self, text: str) -> str:
        """Retrieved chunks / cab notes: drop lines that carry injected instructions before they reach a prompt."""
        return "\n".join(ln for ln in text.splitlines() if not any(p.search(ln) for p in self.patterns))


# ------------------------------------------------------------------ runtime enforcement
class RuntimeRules:
    def __init__(self, cfg: ConfigBundle):
        self.rules = cfg.guardrails["runtime"]["rules"]
        self.params = {k: v for k, v in cfg.guardrails["runtime"].get("vlm", {}).items()}

    def evaluate(self, trigger: str, names: dict[str, Any]) -> GuardDecision:
        ev = EvalWithCompoundTypes(names={**self.params, **names}, functions=SAFE_FUNCTIONS)
        for r in self.rules:
            if r["trigger"] != trigger:
                continue
            try:
                hit = bool(ev.eval(r["when"]))
            except Exception:
                continue  # a rule that cannot evaluate on this context does not apply
            if hit:
                return GuardDecision(r["action"], r["id"], r.get("message_key"))
        return GuardDecision()


# ------------------------------------------------------------------ output guard
@dataclass
class GroundedAnswer:
    text: str
    citations: list[str]
    dropped: list[str]
    cited_sentences: int
    uncited_sentences: int
    numeric_violations: list[str]


def _sentences(answer: str, cite_re: re.Pattern[str]) -> list[str]:
    """Split into sentences, keeping a trailing citation with the sentence it supports.

    Models commonly write "… at 08:00. [plan:T-2045]", which a naive split turns into an uncited claim
    followed by a bare citation.
    """
    parts = [p.strip() for p in _SENT.split(answer.strip()) if p.strip()]
    out: list[str] = []
    for part in parts:
        if out and not cite_re.sub("", part).strip():
            out[-1] = f"{out[-1]} {part}"
            continue
        out.append(part)
    return out


def ground(answer: str, sources: dict[str, str], cfg: ConfigBundle) -> GroundedAnswer:
    """Keep sentences that cite a known source and whose numbers appear in the cited sources."""
    og = cfg.guardrails["output"]
    cite_re = re.compile(og["grounding"]["citation_pattern"])
    exempt = [re.compile(p, re.I) for p in og["grounding"].get("exempt_patterns", [])]
    tol = float(og["numeric"]["tolerance"])
    kept, dropped, used, violations = [], [], [], []
    cited = uncited = 0
    for sent in _sentences(answer, cite_re):
        ids = [c for c in cite_re.findall(sent) if c in sources]
        plain = cite_re.sub("", sent)
        if not ids:
            if any(p.match(plain.strip()) for p in exempt):
                kept.append(sent)
                continue
            uncited += 1
            dropped.append(sent)
            continue
        cited_text = " ".join(sources[c] for c in ids)
        allowed = fact_numbers(cited_text)
        # clock times are checked verbatim (splitting "08:00" into 8 and 0 would compare nothing useful)
        bad = [t for t in _TIME.findall(plain) if t not in cited_text]
        bad += [n for n in _NUM.findall(_TIME.sub(" ", plain)) if not any(abs(float(n) - a) <= tol for a in allowed)]
        if bad:
            violations += bad
            dropped.append(sent)
            continue
        cited += 1
        kept.append(sent)
        used += ids
    text = " ".join(kept) if og["grounding"]["drop_uncited_sentences"] else answer
    for phrase in og["banned_phrases"]:
        if phrase.lower() in text.lower():
            text = ""
            violations.append(f"banned:{phrase}")
    for pat in og["pii"]["patterns"].values():
        text = re.sub(pat, "[redacted]", text)
    return GroundedAnswer(text, sorted(set(used)), dropped, cited, uncited, violations)

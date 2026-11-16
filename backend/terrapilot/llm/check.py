"""`tp llm-check`: verify GROQ_API_KEY, every configured Groq model ID, and rate-limit headroom (§4.1)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from terrapilot.core.config import ConfigBundle, get_config
from terrapilot.core.settings import get_settings
from terrapilot.llm.gateway import parse_target
from terrapilot.llm.providers.base import ProviderError
from terrapilot.llm.types import LLMRequest


def configured_groq_models(cfg: ConfigBundle) -> dict[str, list[str]]:
    """model id → tasks that use it (primary or fallback)."""
    out: dict[str, list[str]] = {}
    for name, task in cfg.llm.tasks.items():
        if task.provider == "groq":
            out.setdefault(task.model, []).append(name)
        for fb in task.fallback:
            t = parse_target(fb)
            if t.provider == "groq":
                out.setdefault(t.model, []).append(f"{name} (fallback)")
    return out


def run_llm_check(ping: bool = True, console: Console | None = None) -> bool:
    console = console or Console()
    settings = get_settings()
    cfg = get_config()
    if settings.tp_profile == "offline":
        console.print("[yellow]TP_PROFILE=offline: Groq is not used; checking configuration only.[/yellow]")
    key = settings.groq_key
    if not key:
        console.print(
            "[red]✗ GROQ_API_KEY is not set.[/red] Add it to .env (see .env.example) — "
            "get a key at https://console.groq.com/keys"
        )
        return False

    from terrapilot.llm.providers.groq_provider import GroqProvider

    groq_cfg = cfg.llm.providers["groq"].model_dump()
    try:
        provider = GroqProvider(key, groq_cfg.get("base_url"))
        available = set(provider.list_models())
    except ProviderError as exc:
        console.print(f"[red]✗ could not list Groq models: {exc}[/red]")
        return False

    wanted = configured_groq_models(cfg)
    table = Table(title="Configured Groq models")
    table.add_column("model")
    table.add_column("status")
    table.add_column("used by")
    missing = []
    for model, tasks in sorted(wanted.items()):
        ok = model in available
        if not ok:
            missing.append(model)
        table.add_row(model, "[green]available[/green]" if ok else "[red]NOT AVAILABLE[/red]", ", ".join(tasks))
    console.print(table)

    healthy = not missing
    if ping:
        task = cfg.llm.tasks["llm_check"]
        req = LLMRequest(
            task="llm_check",
            model=task.model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            temperature=0,
            max_tokens=task.max_tokens,
            timeout_s=(task.timeout_ms or 5000) / 1000,
        )
        try:
            resp = provider.complete(req)
            rate = resp.rate
            console.print(
                f"[green]✓ ping {task.model}[/green] → {resp.text.strip()!r} ({resp.input_tokens}+{resp.output_tokens} tokens)"
            )
            if rate:
                console.print(
                    f"  rate limits: tokens {rate.remaining_tokens}/{rate.limit_tokens} per min, "
                    f"requests {rate.remaining_requests}/{rate.limit_requests} per day"
                )
                configured = cfg.llm.limits.get(task.model)
                if configured and rate.limit_tokens and rate.limit_tokens < configured.tpm:
                    console.print(
                        f"  [yellow]config tpm {configured.tpm} exceeds account limit {rate.limit_tokens} — lower it in llm.yaml[/yellow]"
                    )
        except ProviderError as exc:
            console.print(f"[red]✗ ping failed: {exc}[/red]")
            healthy = False

    if missing:
        console.print(f"[red]✗ {len(missing)} configured model(s) unavailable — update config/llm.yaml[/red]")
    elif healthy:
        console.print("[green]✓ llm-check passed[/green]")
    return healthy

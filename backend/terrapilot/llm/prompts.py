"""Versioned prompt registry (config/prompts/*.j2). The file name carries the version (§12.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

SYSTEM_MARK = "[system]"
USER_MARK = "[user]"


class PromptRegistry:
    def __init__(self, config_root: Path):
        self.root = config_root
        self.env = Environment(
            loader=FileSystemLoader(str(config_root)),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=False,
        )
        self.env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False, default=str)

    @staticmethod
    def version(prompt_path: str) -> str:
        return Path(prompt_path).name.removesuffix(".j2")

    def render(self, prompt_path: str, variables: dict[str, Any]) -> list[dict[str, str]]:
        text = self.env.get_template(Path(prompt_path).as_posix()).render(**variables)
        if SYSTEM_MARK not in text or USER_MARK not in text:
            raise ValueError(f"prompt '{prompt_path}' must contain {SYSTEM_MARK} and {USER_MARK} sections")
        _, rest = text.split(SYSTEM_MARK, 1)
        system, user = rest.split(USER_MARK, 1)
        return [{"role": "system", "content": system.strip()}, {"role": "user", "content": user.strip()}]

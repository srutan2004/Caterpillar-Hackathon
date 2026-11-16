"""Review aid for generated manual sections: every unit-bearing number in a manual must come from the SPEC
VALUES it was generated from. Prints the unsupported numbers per review item.

Usage: uv run python scripts/check_manual_numbers.py [--revise]   (--revise re-asks Groq to fix the numbers)
"""

from __future__ import annotations

import json
import sys

from terrapilot.content.jobs import queue_dir
from terrapilot.content.numbers import unsupported
from terrapilot.content.requests import build_requests, safe_id
from terrapilot.core.config import get_config


def main(argv: list[str]) -> int:
    cfg = get_config()
    reqs = {safe_id(r.custom_id): r for r in build_requests(cfg, "manuals", None)}
    worst = 0
    for path in sorted((queue_dir() / "manuals").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        req = reqs.get(item["id"])
        if req is None:
            print(f"{item['id']}: no source request")
            continue
        bad = unsupported(item["content"], req.variables)
        if bad and "--revise" in argv:
            from rich.console import Console

            from terrapilot.content.jobs import _numeric_revise
            from terrapilot.llm.gateway import get_gateway

            item["content"], bad = _numeric_revise(get_gateway(), req, item["content"], Console())
            item["meta"] = {**item["meta"], "unsupported_numbers": bad or []}
            path.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
        worst = max(worst, len(bad or []))
        print(f"{item['id']}: {len(bad)} unsupported: {', '.join(bad[:12])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

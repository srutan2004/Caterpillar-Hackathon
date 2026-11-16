"""Hardcoding gate (§2.1): fail if apps/web/src contains hex colours, rgb(), px literals outside the
theme adapter, or http(s) URLs. Complements the ESLint rules (no magic numbers, no JSX literals).

Usage: uv run python scripts/check_hardcoding.py [paths...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "apps" / "web" / "src"
EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".css"}
# The theme adapter is the one place allowed to handle raw token values; generated API types are exempt.
ALLOWED = {"runtime/theme.ts", "api/schema.d.ts"}
TEST_SUFFIXES = (".test.ts", ".test.tsx")

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("hex colour", re.compile(r"(?<![\w&])#[0-9a-fA-F]{3,8}\b(?![-\w])")),
    ("rgb()/rgba()/hsl()", re.compile(r"\b(?:rgba?|hsla?)\(")),
    ("px literal", re.compile(r"(?<![\w-])\d+(?:\.\d+)?px\b")),
    ("hardcoded URL", re.compile(r"[\"'`]https?://")),
]


def scan(path: Path, base: Path) -> list[str]:
    rel = path.relative_to(base).as_posix()
    if rel in ALLOWED or rel.endswith(TEST_SUFFIXES):
        return []
    problems = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "/*", "*")):
            continue
        for name, pattern in RULES:
            if pattern.search(line):
                problems.append(f"{rel}:{lineno}: {name}: {stripped[:120]}")
    return problems


def main(argv: list[str]) -> int:
    targets = [Path(a).resolve() for a in argv] or [DEFAULT_TARGET]
    problems: list[str] = []
    for target in targets:
        base = target if target.is_dir() else target.parent
        files = [target] if target.is_file() else [p for p in target.rglob("*") if p.suffix in EXTENSIONS]
        for f in sorted(files):
            problems += scan(f, base if target.is_file() else target)
    for p in problems:
        print(p)
    if problems:
        print(f"✗ {len(problems)} hardcoding violation(s) — move values to config/ (theme.yaml, i18n, app.yaml)")
        return 1
    print(f"✓ no hardcoded colours, pixel sizes or URLs in {', '.join(str(t.relative_to(ROOT)) for t in targets)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(main(sys.argv[1:]))

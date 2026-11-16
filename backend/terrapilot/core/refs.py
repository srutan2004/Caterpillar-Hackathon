"""Reference resolution for config files (§6).

Two kinds of references exist:

* ``ref:<target>`` *values* are inlined at load time. ``<target>`` is either a path inside the same
  document (``ref:specs.derived.tail_swing_radius``) or a file relative to the config root, optionally
  with a key path (``ref:walkaround/excavator.yaml`` or ``ref:maintenance/x.yaml#a.b``).
* ``*_ref`` *keys* and ``manifest.<path>`` / ``app.<path>`` expressions stay as pointers; they are
  validated to exist (see ``config.py``) but not inlined, so a threshold has exactly one source.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REF_PREFIX = "ref:"


class RefError(ValueError):
    pass


def get_path(doc: Any, dotted: str) -> Any:
    """Resolve ``a.b.c`` (or ``a.0.b`` for list indices) inside a nested structure."""
    node = doc
    for part in [p for p in dotted.split(".") if p]:
        if isinstance(node, dict):
            if part not in node:
                raise RefError(f"key '{part}' not found while resolving '{dotted}'")
            node = node[part]
        elif isinstance(node, list):
            if part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                # allow lookup of list items by their `id` / `item` field
                match = next((x for x in node if isinstance(x, dict) and part in (x.get("id"), x.get("item"))), None)
                if match is None:
                    raise RefError(f"list item '{part}' not found while resolving '{dotted}'")
                node = match
        else:
            raise RefError(f"cannot descend into scalar at '{part}' while resolving '{dotted}'")
    return node


def has_path(doc: Any, dotted: str) -> bool:
    try:
        get_path(doc, dotted)
    except RefError:
        return False
    return True


def split_file_ref(target: str) -> tuple[str, str | None]:
    """``maintenance/x.yaml#a.b`` → (``maintenance/x.yaml``, ``a.b``)."""
    if "#" in target:
        file_part, key = target.split("#", 1)
        return file_part, key or None
    return target, None


def is_file_ref(target: str) -> bool:
    return split_file_ref(target)[0].endswith((".yaml", ".yml", ".json"))


def load_file_ref(config_root: Path, target: str, loader: Callable[[Path], Any] | None = None) -> Any:
    file_part, key = split_file_ref(target)
    path = (config_root / file_part).resolve()
    if not path.is_file():
        raise RefError(f"referenced file '{file_part}' does not exist")
    data = loader(path) if loader else yaml.safe_load(path.read_text(encoding="utf-8"))
    return get_path(data, key) if key else data


def resolve_inline_refs(doc: Any, config_root: Path, root: Any | None = None, trail: str = "") -> Any:
    """Return a copy of ``doc`` with every ``ref:`` string value inlined."""
    root = doc if root is None else root
    if isinstance(doc, dict):
        return {
            k: resolve_inline_refs(v, config_root, root, f"{trail}.{k}" if trail else str(k)) for k, v in doc.items()
        }
    if isinstance(doc, list):
        return [resolve_inline_refs(v, config_root, root, f"{trail}.{i}") for i, v in enumerate(doc)]
    if isinstance(doc, str) and doc.startswith(REF_PREFIX):
        target = doc[len(REF_PREFIX) :].strip()
        try:
            if is_file_ref(target):
                return load_file_ref(config_root, target)
            value = get_path(root, target)
        except RefError as exc:
            raise RefError(f"{trail}: {exc}") from exc
        if isinstance(value, str) and value.startswith(REF_PREFIX):
            raise RefError(f"{trail}: chained refs are not supported ('{target}')")
        return value
    return doc


@lru_cache(maxsize=256)
def _cached_ref(config_root: Path, target: str) -> Any:
    return load_file_ref(config_root, target)


def load_ref_cached(config_root: Path, target: str) -> Any:
    """Runtime lookups of config values (read-only): parsed once per process, deep-copied per call."""
    return copy.deepcopy(_cached_ref(config_root, target))

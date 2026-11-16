"""Shared fixtures. Tests never touch Groq (cassettes) and API tests run on SQLite."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ["TP_ENV"] = "test"
os.environ["TP_LLM_CASSETTE"] = "off"  # cassette replay is exercised explicitly in test_llm_gateway

from terrapilot.core.config import ConfigBundle, load_config
from terrapilot.core.settings import REPO_ROOT

ANCHOR = "2026-09-23"


@pytest.fixture(scope="session")
def cfg() -> ConfigBundle:
    return load_config(REPO_ROOT / "config")


@pytest.fixture()
def config_copy(tmp_path: Path) -> Path:
    """A writable copy of config/ for tests that mutate YAML."""
    dst = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", dst)
    return dst


@pytest.fixture(scope="session")
def tiny_data(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from rich.console import Console

    from terrapilot.datagen.pipeline import run_generation

    out = tmp_path_factory.mktemp("generated")
    run_generation(scale="tiny", seed=42, out_dir=out, anchor=ANCHOR, console=Console(quiet=True))
    yield out

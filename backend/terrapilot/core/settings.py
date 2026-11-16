"""Environment settings (pydantic-settings). Domain constants never live here; they come from YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` until a directory containing both `config/` and `pyproject.toml` is found."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "config").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


REPO_ROOT = find_repo_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    tp_profile: Literal["online", "offline"] = "online"
    tp_env: Literal["dev", "test", "prod"] = "dev"
    tp_config_dir: Path = Path("config")
    tp_data_dir: Path = Path("data")

    groq_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"

    database_url: str = "postgresql+psycopg://terrapilot:change-me-postgres@localhost:5432/terrapilot"
    tp_ro_password: SecretStr = SecretStr("change-me-readonly")
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"

    # Demo clock: an ISO timestamp (or local "HH:MM" today) that planning/shift views treat as "now".
    tp_now: str | None = None

    jwt_secret: SecretStr = SecretStr("dev-only-jwt-secret")
    cors_origins: str = Field(default="http://localhost:5173")

    @property
    def config_dir(self) -> Path:
        p = self.tp_config_dir
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def data_dir(self) -> Path:
        p = self.tp_data_dir
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def groq_key(self) -> str | None:
        if self.groq_api_key is None:
            return None
        value = self.groq_api_key.get_secret_value().strip()
        return value or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

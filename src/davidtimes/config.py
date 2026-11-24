"""Load and validate config/sources.yaml and config/llm.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(os.environ.get("DAVIDTIMES_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = ROOT / "config"
TEMPLATES_DIR = ROOT / "templates"
DIST_DIR = Path(os.environ.get("DAVIDTIMES_DIST", ROOT / "dist"))
CACHE_DIR = Path(os.environ.get("DAVIDTIMES_CACHE_DIR", ROOT / ".cache"))


class Settings(BaseModel):
    reading_time_minutes: int = 30
    words_per_minute: int = 220
    lookback_hours: int = 36
    words_per_piece: int = 350
    max_article_chars: int = 6000
    min_article_chars: int = 600
    max_sources_per_cluster: int = 3
    extra_candidates: int = 2
    timezone: str = "America/Bogota"
    user_agent: str = "DavidTimes/0.1 (personal RSS reader)"


class Source(BaseModel):
    # Extra keys (url, tag, section, competition...) are per-type parameters.
    model_config = ConfigDict(extra="allow")
    type: str
    name: str
    enabled: bool = True

    def param(self, key: str, default: Any = None) -> Any:
        return (self.model_extra or {}).get(key, default)


class Section(BaseModel):
    id: str
    name: str
    language: Literal["es", "en"] = "es"
    weight: float = 1.0
    recap_mode: str | None = None
    sources: list[Source]


class SourcesConfig(BaseModel):
    settings: Settings = Field(default_factory=Settings)
    sections: list[Section]


class Provider(BaseModel):
    name: str
    base_url: str
    api_key_env: str
    models: dict[str, str]
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    json_mode: bool | None = None

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


class LLMConfig(BaseModel):
    requests_per_minute: int = 8
    max_calls_per_run: int = 40
    temperature: float = 0.3
    timeout_seconds: float = 120
    json_mode: bool = True
    providers: list[Provider]


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_sources(path: Path | None = None) -> SourcesConfig:
    return SourcesConfig.model_validate(_load_yaml(path or CONFIG_DIR / "sources.yaml"))


def load_llm(path: Path | None = None) -> LLMConfig:
    return LLMConfig.model_validate(_load_yaml(path or CONFIG_DIR / "llm.yaml"))

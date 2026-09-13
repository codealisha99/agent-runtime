"""Environment-driven settings. Mock provider works with no API keys."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "mock"
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    redis_url: str = ""
    cache_backend: str = "auto"
    otel_endpoint: str = "http://localhost:4318"
    workspace_dir: str = ""
    tool_timeout: int = 5
    tool_retries: int = 2
    sandbox_timeout: int = 2


def get_settings() -> Settings:
    return Settings(
        llm_provider=_env("LLM_PROVIDER", "mock").lower(),
        openai_api_key=_env("OPENAI_API_KEY"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434"),
        redis_url=_env("REDIS_URL"),
        cache_backend=_env("CACHE_BACKEND", "auto").lower(),
        otel_endpoint=_env("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
        workspace_dir=_env("WORKSPACE_DIR", ""),
        tool_timeout=_env_int("TOOL_TIMEOUT", 5),
        tool_retries=_env_int("TOOL_RETRIES", 2),
        sandbox_timeout=_env_int("SANDBOX_TIMEOUT", 2),
    )

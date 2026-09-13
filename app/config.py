"""Environment-driven settings. Mock provider works with no API keys."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    llm_provider: str = "mock"
    llm_fallback: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    redis_url: str = ""
    cache_backend: str = "auto"
    otel_endpoint: str = "http://localhost:4318"
    workspace_dir: str = ""
    tool_timeout: int = 5
    tool_retries: int = 2
    sandbox_timeout: int = 2
    search_provider: str = "auto"
    brave_api_key: str = ""
    weather_provider: str = "auto"
    translate_provider: str = "auto"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@localhost"
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    http_timeout: int = 8
    injection_threshold: float = 0.72
    rate_limit_per_minute: int = 0
    max_input_chars: int = 16000


def get_settings() -> Settings:
    app_env = _env("APP_ENV", "development").lower()
    fallback = _env("LLM_FALLBACK")
    if not fallback:
        fallback = "none" if app_env == "production" else "mock"
    return Settings(
        app_env=app_env,
        llm_provider=_env("LLM_PROVIDER", "mock").lower(),
        llm_fallback=fallback.lower(),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_model=_env("OPENAI_MODEL", "gpt-4o-mini"),
        openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=_env("OLLAMA_MODEL", "llama3.2"),
        redis_url=_env("REDIS_URL"),
        cache_backend=_env("CACHE_BACKEND", "auto").lower(),
        otel_endpoint=_env("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
        workspace_dir=_env("WORKSPACE_DIR", ""),
        tool_timeout=_env_int("TOOL_TIMEOUT", 5),
        tool_retries=_env_int("TOOL_RETRIES", 2),
        sandbox_timeout=_env_int("SANDBOX_TIMEOUT", 2),
        search_provider=_env("SEARCH_PROVIDER", "auto").lower(),
        brave_api_key=_env("BRAVE_API_KEY"),
        weather_provider=_env("WEATHER_PROVIDER", "auto").lower(),
        translate_provider=_env("TRANSLATE_PROVIDER", "auto").lower(),
        smtp_host=_env("SMTP_HOST"),
        smtp_port=_env_int("SMTP_PORT", 587),
        smtp_user=_env("SMTP_USER"),
        smtp_password=_env("SMTP_PASSWORD"),
        smtp_from=_env("SMTP_FROM", "noreply@localhost"),
        smtp_starttls=_env_bool("SMTP_STARTTLS", True),
        smtp_ssl=_env_bool("SMTP_SSL", False),
        http_timeout=_env_int("HTTP_TIMEOUT", 8),
        injection_threshold=float(_env("INJECTION_THRESHOLD", "0.72")),
        rate_limit_per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 0),
        max_input_chars=_env_int("MAX_INPUT_CHARS", 16000),
    )

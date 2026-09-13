"""LLM hop: mock | OpenAI | Ollama. Production fails closed unless LLM_FALLBACK=mock."""
from __future__ import annotations

import logging
import re

from ..config import get_settings
from ..observability.otel import span

log = logging.getLogger("agentruntime.llm")


class LLMError(RuntimeError):
    pass


def complete(prompt: str) -> str:
    settings = get_settings()
    provider = settings.llm_provider
    with span("llm.complete", provider=provider):
        try:
            if provider == "openai":
                return _openai_chat(prompt)
            if provider == "ollama":
                return _ollama_chat(prompt)
            if provider != "mock":
                raise LLMError(f"unknown LLM_PROVIDER: {provider}")
            return _mock(prompt)
        except Exception as exc:
            if settings.llm_fallback == "mock" and provider != "mock":
                log.warning("llm provider %s failed, falling back to mock: %s", provider, exc)
                return _mock(prompt)
            if isinstance(exc, LLMError):
                raise
            raise LLMError(str(exc)) from exc


def probe() -> dict:
    settings = get_settings()
    provider = settings.llm_provider
    if provider == "mock":
        return {"provider": "mock", "ok": True, "model": "mock"}
    if provider == "openai":
        return {
            "provider": "openai",
            "ok": bool(settings.openai_api_key),
            "model": settings.openai_model,
            "error": None if settings.openai_api_key else "OPENAI_API_KEY missing",
        }
    if provider == "ollama":
        return {"provider": "ollama", "ok": True, "model": settings.ollama_model}
    return {"provider": provider, "ok": False, "error": "unknown provider"}


def plan_tool(user_input: str) -> dict | None:
    text = user_input.strip()
    calc_match = re.search(r"(?:calc(?:ulate)?|what is|compute)\s+([0-9+\-*/(). ]+)", text, re.I)
    if calc_match:
        return {"name": "calc", "args": {"expression": calc_match.group(1).strip()}}
    weather = re.search(r"weather(?:\s+in)?\s+([A-Za-z][A-Za-z\s]+)$", text, re.I)
    if weather:
        return {"name": "get_weather", "args": {"city": weather.group(1).strip()}}
    translate = re.search(r"translate\s+(.+?)\s+to\s+([A-Za-z]{2,})\b", text, re.I)
    if translate:
        return {"name": "translate", "args": {"text": translate.group(1).strip(), "target": translate.group(2).strip()}}
    search = re.search(r"(?:search|look up)\s+(.+)", text, re.I)
    if search:
        return {"name": "search_web", "args": {"query": search.group(1).strip()}}
    summary = re.search(r"summarize\s+(\S+)", text, re.I)
    if summary:
        return {"name": "summarize", "args": {"doc_id": summary.group(1).strip()}}
    return None


def _mock(prompt: str) -> str:
    compact = " ".join(prompt.split())
    return f"[mock] {compact[:360]}"


def _openai_chat(prompt: str) -> str:
    import httpx

    settings = get_settings()
    if not settings.openai_api_key:
        raise LLMError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    resp = httpx.post(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
        json={
            "model": settings.openai_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        },
        timeout=settings.http_timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    if not content:
        raise LLMError("openai returned an empty completion")
    return content


def _ollama_chat(prompt: str) -> str:
    import httpx

    settings = get_settings()
    resp = httpx.post(
        f"{settings.ollama_base_url.rstrip('/')}/api/generate",
        json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
        timeout=max(settings.http_timeout, 30),
    )
    resp.raise_for_status()
    content = resp.json().get("response", "")
    if not content:
        raise LLMError("ollama returned an empty completion")
    return content

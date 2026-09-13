"""Shared HTTP client with timeouts."""
from __future__ import annotations

import httpx

from ..config import get_settings

USER_AGENT = "AgentRuntime/2.0 (+https://localhost:8004)"


def client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=settings.http_timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )

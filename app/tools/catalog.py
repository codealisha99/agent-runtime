"""Static catalogs used when live providers are off or fail."""
from __future__ import annotations

from typing import Any

CORPUS: dict[str, dict[str, str]] = {
    "agent-runtime": {
        "title": "AgentRuntime",
        "text": (
            "AgentRuntime is a permissioned tool runtime. Every tool has a JSON Schema, "
            "an allowed_capabilities list, and runs inside a tenant workspace. "
            "run_python is AST-validated and executed in an isolated subprocess. "
            "Guardrails redact PII and honor block, flag, or transform injection policies."
        ),
    },
    "guardrails": {
        "title": "GuardRail",
        "text": (
            "Guardrails scan input and output for emails, phones, SSNs, payment cards, "
            "and API keys. Prompt-injection phrases such as ignore previous instructions "
            "are blocked, flagged, or stripped. wrap_llm applies the same policy to any callable."
        ),
    },
    "sandbox": {
        "title": "Python sandbox",
        "text": (
            "The sandbox allows math, json, time, and other safe stdlib modules. "
            "Imports of os, sys, socket, and file open() are denied. Code cannot leave the temp directory."
        ),
    },
    "grants": {
        "title": "Capability grants",
        "text": (
            "Server-side grants are stored per tenant. Once a grant row exists, body capabilities "
            "are ignored. Missing capabilities return HTTP 403."
        ),
    },
}

WEATHER: dict[str, dict[str, Any]] = {
    "san francisco": {"temp_c": 16, "condition": "fog", "humidity": 82},
    "new york": {"temp_c": 22, "condition": "partly cloudy", "humidity": 61},
    "london": {"temp_c": 14, "condition": "rain", "humidity": 88},
    "tokyo": {"temp_c": 24, "condition": "clear", "humidity": 55},
    "mumbai": {"temp_c": 31, "condition": "humid", "humidity": 74},
    "berlin": {"temp_c": 18, "condition": "overcast", "humidity": 66},
}

PHRASES = {
    "es": {
        "hello": "hola",
        "thank you": "gracias",
        "please": "por favor",
        "good morning": "buenos días",
        "how are you": "cómo estás",
    },
    "fr": {
        "hello": "bonjour",
        "thank you": "merci",
        "please": "s'il vous plaît",
        "good morning": "bonjour",
        "how are you": "comment allez-vous",
    },
    "de": {
        "hello": "hallo",
        "thank you": "danke",
        "please": "bitte",
        "good morning": "guten morgen",
        "how are you": "wie geht's",
    },
}

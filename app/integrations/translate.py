"""Live translation via MyMemory, with a phrasebook fallback."""
from __future__ import annotations

import re
from typing import Any

from ..config import get_settings
from ..tools.catalog import PHRASES
from .http import client


def translate(text: str, target: str) -> dict[str, Any]:
    settings = get_settings()
    provider = settings.translate_provider
    if provider == "phrasebook":
        return _phrasebook(text, target)
    if provider in {"auto", "live", "mymemory"}:
        try:
            return _mymemory(text, target)
        except Exception:
            if provider != "auto":
                raise
    return {**_phrasebook(text, target), "fallback": True}


def _phrasebook(text: str, target: str) -> dict[str, Any]:
    lang = target.strip().lower()
    table = PHRASES.get(lang, {})
    low = text.strip().lower()
    if low in table:
        return {"text": text, "target": lang, "translated": table[low], "engine": "phrasebook"}
    if table:
        words = [table.get(w, w) for w in re.findall(r"[A-Za-z']+|[^A-Za-z']+", text)]
        return {"text": text, "target": lang, "translated": "".join(words), "engine": "wordmap"}
    return {"text": text, "target": lang, "translated": f"[{lang}] {text}", "engine": "passthrough"}


def _mymemory(text: str, target: str) -> dict[str, Any]:
    lang = target.strip().lower()
    with client() as http:
        resp = http.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text, "langpair": f"en|{lang}"},
        )
        resp.raise_for_status()
        data = resp.json()
    translated = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    if not translated:
        raise RuntimeError("empty translation")
    return {"text": text, "target": lang, "translated": translated, "engine": "mymemory"}

"""Live web search: Brave (key) → DuckDuckGo JSON → Wikipedia → corpus."""
from __future__ import annotations

import re
from typing import Any

from ..config import get_settings
from ..tools.catalog import CORPUS
from .http import client


def corpus_search(query: str) -> dict[str, Any]:
    q = query.lower().strip()
    hits = []
    for doc_id, doc in CORPUS.items():
        blob = f"{doc['title']} {doc['text']}".lower()
        score = sum(1 for tok in re.findall(r"[a-z0-9]+", q) if tok in blob)
        if score:
            hits.append(
                {
                    "title": doc["title"],
                    "snippet": doc["text"][:180],
                    "url": f"corpus://{doc_id}",
                    "score": score,
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return {"query": query, "hits": hits[:5], "source": "corpus"}


def search_web(query: str) -> dict[str, Any]:
    settings = get_settings()
    provider = settings.search_provider
    if provider == "corpus":
        return corpus_search(query)

    errors: list[str] = []
    if provider in {"auto", "brave"} and settings.brave_api_key:
        try:
            return _brave(query, settings.brave_api_key)
        except Exception as exc:
            errors.append(f"brave: {exc}")
            if provider == "brave":
                raise RuntimeError(str(exc)) from exc

    if provider in {"auto", "ddg", "live"}:
        try:
            live = _ddg(query)
            if live["hits"]:
                return live
            errors.append("ddg: empty")
        except Exception as exc:
            errors.append(f"ddg: {exc}")
            if provider == "ddg":
                raise RuntimeError(str(exc)) from exc
        try:
            wiki = _wikipedia(query)
            if wiki["hits"]:
                return wiki
        except Exception as exc:
            errors.append(f"wikipedia: {exc}")

    fallback = corpus_search(query)
    fallback["fallback"] = True
    fallback["errors"] = errors
    return fallback


def _brave(query: str, token: str) -> dict[str, Any]:
    with client() as http:
        resp = http.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": token, "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    hits = []
    for item in (data.get("web") or {}).get("results") or []:
        hits.append(
            {
                "title": item.get("title") or "",
                "snippet": item.get("description") or "",
                "url": item.get("url") or "",
            }
        )
    return {"query": query, "hits": hits[:5], "source": "brave"}


def _ddg(query: str) -> dict[str, Any]:
    with client() as http:
        resp = http.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
        )
        resp.raise_for_status()
        data = resp.json()
    hits: list[dict[str, str]] = []
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        hits.append(
            {
                "title": data.get("Heading") or query,
                "snippet": abstract[:280],
                "url": data.get("AbstractURL") or "",
            }
        )
    for topic in data.get("RelatedTopics") or []:
        if not isinstance(topic, dict):
            continue
        text = topic.get("Text") or ""
        url = topic.get("FirstURL") or ""
        if text:
            hits.append({"title": text.split(" - ", 1)[0][:80], "snippet": text[:280], "url": url})
        if len(hits) >= 5:
            break
    return {"query": query, "hits": hits[:5], "source": "ddg"}


def _wikipedia(query: str) -> dict[str, Any]:
    with client() as http:
        resp = http.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "opensearch", "search": query, "limit": 5, "namespace": 0, "format": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
    titles = data[1] if len(data) > 1 else []
    snippets = data[2] if len(data) > 2 else []
    urls = data[3] if len(data) > 3 else []
    hits = []
    for title, snippet, url in zip(titles, snippets, urls):
        hits.append({"title": title, "snippet": snippet or title, "url": url})
    return {"query": query, "hits": hits[:5], "source": "wikipedia"}

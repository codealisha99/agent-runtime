"""Tool registry: schemas, discovery, grants, timeout, retries, logging."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Callable

from ..config import get_settings
from . import handlers

TOOLS: dict[str, dict[str, Any]] = {}
LOGS: list[dict[str, Any]] = []
GRANTS: dict[str, list[str]] = {}


def register_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: Callable,
    allowed_capabilities: list[str] | None = None,
    timeout: int | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise ValueError("tool name must be lowercase with underscores")
    if name in TOOLS and not replace:
        raise ValueError(f"tool {name} already registered")
    TOOLS[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "allowed_capabilities": allowed_capabilities or [],
        "timeout": timeout or get_settings().tool_timeout,
        "created_at": time.time(),
    }
    return TOOLS[name]


def list_tools(query: str | None = None) -> list[dict[str, Any]]:
    items = [
        {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
            "allowed_capabilities": t["allowed_capabilities"],
            "timeout": t["timeout"],
        }
        for t in TOOLS.values()
    ]
    if query:
        q = query.lower()
        items = [i for i in items if q in i["name"] or q in i["description"].lower()]
    return items


def validate_args(tool: dict[str, Any], args: dict[str, Any]) -> str | None:
    schema = tool["parameters"]
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in args:
            return f"missing required param: {key}"
    for key, value in args.items():
        if key not in props:
            return f"unknown param: {key}"
        expected = props[key].get("type")
        if expected == "string" and not isinstance(value, str):
            return f"param {key} must be string"
        if expected == "integer" and not isinstance(value, int):
            return f"param {key} must be integer"
        if expected == "number" and not isinstance(value, (int, float)):
            return f"param {key} must be number"
        if expected == "boolean" and not isinstance(value, bool):
            return f"param {key} must be boolean"
    return None


def check_permission(tool: dict[str, Any], requester_capabilities: list[str]) -> bool:
    needed = set(tool["allowed_capabilities"])
    if not needed:
        return True
    return needed.issubset(set(requester_capabilities))


def _redis():
    settings = get_settings()
    if settings.cache_backend == "memory" or not settings.redis_url:
        return None
    try:
        import redis

        client = redis.from_url(settings.redis_url)
        client.ping()
        return client
    except Exception:
        return None


def persist() -> None:
    client = _redis()
    if client is None:
        return
    client.set("agent:grants", json.dumps(GRANTS))


def hydrate() -> None:
    client = _redis()
    if client is None:
        return
    raw = client.get("agent:grants")
    if not raw:
        return
    GRANTS.clear()
    GRANTS.update(json.loads(raw))


def grant(tenant_id: str, capabilities: list[str]) -> list[str]:
    GRANTS[tenant_id] = sorted(set(capabilities))
    persist()
    return GRANTS[tenant_id]


def grants_for(tenant_id: str) -> list[str] | None:
    return GRANTS.get(tenant_id)


def capabilities_for(tenant_id: str, requester_capabilities: list[str] | None) -> list[str]:
    if tenant_id in GRANTS:
        return GRANTS[tenant_id]
    return requester_capabilities or []


def _run_with_timeout(handler: Callable, timeout: int, args: dict[str, Any]) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(handler, **args)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout as exc:
            raise TimeoutError("tool timed out") from exc


def execute_tool(
    name: str,
    args: dict[str, Any],
    requester_capabilities: list[str] | None = None,
    timeout: int | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    settings = get_settings()
    requester_capabilities = capabilities_for(tenant_id, requester_capabilities)
    if name not in TOOLS:
        return {"error": f"tool {name} not found", "status": 404, "tenant_id": tenant_id}
    tool = TOOLS[name]
    err = validate_args(tool, args)
    if err:
        return {"error": err, "status": 400, "tenant_id": tenant_id}
    if tool["allowed_capabilities"] and not check_permission(tool, requester_capabilities):
        return {
            "error": f"permission denied for tool {name}: requires {tool['allowed_capabilities']}",
            "status": 403,
            "tenant_id": tenant_id,
        }

    limit = timeout or tool.get("timeout") or settings.tool_timeout
    retries = max(1, settings.tool_retries)
    last = None
    token = handlers.set_tenant(tenant_id)
    try:
        for attempt in range(retries):
            try:
                result = _run_with_timeout(tool["handler"], limit, args)
                LOGS.append(
                    {
                        "tool": name,
                        "args": args,
                        "result": result,
                        "ts": time.time(),
                        "capabilities": requester_capabilities,
                        "tenant_id": tenant_id,
                        "status": 200,
                    }
                )
                return {
                    "result": result,
                    "status": 200,
                    "retries": attempt,
                    "tenant_id": tenant_id,
                }
            except PermissionError as exc:
                last = str(exc)
                LOGS.append(
                    {
                        "tool": name,
                        "args": args,
                        "error": last,
                        "ts": time.time(),
                        "capabilities": requester_capabilities,
                        "tenant_id": tenant_id,
                        "status": 403,
                    }
                )
                return {"error": last, "status": 403, "tenant_id": tenant_id}
            except TimeoutError as exc:
                last = str(exc)
                return {"error": last, "status": 408, "retries": attempt, "tenant_id": tenant_id}
            except ValueError as exc:
                last = str(exc)
                return {"error": last, "status": 400, "tenant_id": tenant_id}
            except FileNotFoundError as exc:
                last = str(exc)
                return {"error": last, "status": 404, "tenant_id": tenant_id}
            except Exception as exc:
                last = str(exc)
        return {"error": last or "tool failed", "status": 500, "retries": retries - 1, "tenant_id": tenant_id}
    finally:
        handlers.reset_tenant(token)


def clear() -> None:
    TOOLS.clear()
    LOGS.clear()
    GRANTS.clear()
    handlers.EMAIL_OUTBOX.clear()


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def _init_demo() -> None:
    clear()
    register_tool(
        "search_web",
        "Search the internal knowledge corpus",
        _schema({"query": {"type": "string"}}, ["query"]),
        handlers.search_web,
        ["network"],
    )
    register_tool(
        "read_file",
        "Read a file from the tenant workspace",
        _schema({"path": {"type": "string"}}, ["path"]),
        handlers.read_file,
        ["filesystem"],
    )
    register_tool(
        "write_file",
        "Write a file into the tenant workspace",
        _schema({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
        handlers.write_file,
        ["filesystem"],
    )
    register_tool(
        "run_python",
        "Execute Python in an isolated sandbox",
        _schema({"code": {"type": "string"}}, ["code"]),
        handlers.run_python,
        ["sandbox"],
        timeout=get_settings().sandbox_timeout + 2,
    )
    register_tool(
        "query_db",
        "Read-only SQL against the tenant catalog",
        _schema({"sql": {"type": "string"}}, ["sql"]),
        handlers.query_db,
        ["database"],
    )
    register_tool(
        "send_email",
        "Queue an outbound email for the tenant",
        _schema(
            {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            ["to", "subject"],
        ),
        handlers.send_email,
        ["network"],
    )
    register_tool(
        "get_weather",
        "Look up weather for a city",
        _schema({"city": {"type": "string"}}, ["city"]),
        handlers.get_weather,
        ["network"],
    )
    register_tool(
        "calc",
        "Evaluate an arithmetic expression",
        _schema({"expression": {"type": "string"}}, ["expression"]),
        handlers.calc,
        [],
    )
    register_tool(
        "translate",
        "Translate short text into a target language",
        _schema({"text": {"type": "string"}, "target": {"type": "string"}}, ["text", "target"]),
        handlers.translate,
        ["network"],
    )
    register_tool(
        "summarize",
        "Summarize a corpus document or workspace file",
        _schema({"doc_id": {"type": "string"}}, ["doc_id"]),
        handlers.summarize,
        [],
    )


_init_demo()
hydrate()

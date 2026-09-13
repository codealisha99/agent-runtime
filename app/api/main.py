"""AgentRuntime FastAPI — typed tools, grants, sandbox, guardrails."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..guardrails.middleware import check_input, check_output, redact_pii, wrap_llm
from ..llm.provider import LLMError, complete, plan_tool, probe
from ..observability.otel import current_trace_id, init_tracing, span
from ..tools import handlers
from ..tools.registry import (
    GRANTS,
    LOGS,
    TOOLS,
    _redis,
    execute_tool,
    grant,
    grants_for,
    list_tools,
    register_tool,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agentruntime")

settings = get_settings()
init_tracing("agentruntime", settings.otel_endpoint)

app = FastAPI(
    title="AgentRuntime",
    version="2.0.0",
    description="Production runtime: typed tools, SMTP, live search, trained injection classifier, OpenAI/Ollama.",
)

DASHBOARD = Path(__file__).with_name("dashboard.html")


def resolve_tenant(explicit: str | None, header_value: str | None) -> str:
    return (header_value or explicit or "default").strip() or "default"


class ToolRegister(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    allowed_capabilities: list[str] = []


class ToolExec(BaseModel):
    name: str
    args: dict[str, Any] = {}
    capabilities: list[str] = []
    timeout: Optional[int] = None


class GrantBody(BaseModel):
    capabilities: list[str]
    tenant_id: str = "default"


class GuardCheck(BaseModel):
    text: str = Field(..., max_length=16000)
    policy: str = "block"
    direction: str = "input"


class RedactBody(BaseModel):
    text: str = Field(..., max_length=16000)


class ToolRequest(BaseModel):
    name: str
    args: dict[str, Any] = {}


class AgentExec(BaseModel):
    input: str = Field(..., max_length=16000)
    tool_request: Optional[ToolRequest] = None
    capabilities: list[str] = []
    policy: str = "block"
    tenant_id: str = "default"


class WrapDemo(BaseModel):
    prompt: str
    policy: str = "block"


def _checks() -> dict[str, Any]:
    cfg = get_settings()
    redis_client = _redis()
    return {
        "llm": probe(),
        "smtp": {
            "configured": bool(cfg.smtp_host),
            "ok": True,
            "from": cfg.smtp_from if cfg.smtp_host else None,
        },
        "search": {"provider": cfg.search_provider, "brave": bool(cfg.brave_api_key)},
        "weather": {"provider": cfg.weather_provider},
        "translate": {"provider": cfg.translate_provider},
        "cache": {
            "backend": "memory" if cfg.cache_backend == "memory" or not cfg.redis_url else "redis",
            "ok": cfg.cache_backend == "memory" or redis_client is not None,
        },
        "injection": {"classifier": "naive_bayes", "threshold": cfg.injection_threshold},
    }


@app.get("/health")
def health():
    cfg = get_settings()
    return {
        "status": "ok",
        "service": "agentruntime",
        "version": "2.0.0",
        "env": cfg.app_env,
        "tools": len(TOOLS),
        "grants": len(GRANTS),
        "logs": len(LOGS),
        "outbox": len(handlers.EMAIL_OUTBOX),
        "llm": cfg.llm_provider,
        "checks": _checks(),
    }


@app.get("/ready")
def ready():
    cfg = get_settings()
    checks = _checks()
    problems = []
    if cfg.llm_provider == "openai" and not cfg.openai_api_key:
        problems.append("OPENAI_API_KEY missing")
    if cfg.cache_backend == "redis" and not checks["cache"]["ok"]:
        problems.append("redis unavailable")
    if problems and cfg.app_env == "production":
        return JSONResponse({"status": "not_ready", "problems": problems, "checks": checks}, status_code=503)
    return {"status": "ready", "problems": problems, "checks": checks}


@app.post("/v1/tools/register")
def post_register(body: ToolRegister):
    def handler(**kwargs):
        return {"tool": body.name, "args": kwargs, "dynamic": True}

    try:
        tool = register_tool(
            body.name,
            body.description,
            body.parameters,
            handler,
            body.allowed_capabilities,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"tool": {"name": tool["name"], "description": tool["description"]}}


@app.get("/v1/tools")
def get_tools(q: Optional[str] = None):
    return {"tools": list_tools(q)}


@app.post("/v1/grants")
def post_grants(body: GrantBody, x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    tid = resolve_tenant(body.tenant_id, x_tenant_id)
    return {"tenant_id": tid, "capabilities": grant(tid, body.capabilities)}


@app.get("/v1/grants")
def get_grants(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"), tenant_id: str = "default"):
    tid = resolve_tenant(tenant_id, x_tenant_id)
    caps = grants_for(tid)
    return {"tenant_id": tid, "capabilities": caps or [], "granted": tid in GRANTS}


@app.post("/v1/tools/execute")
def post_execute(body: ToolExec, x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    tid = resolve_tenant(None, x_tenant_id)
    with span("agent.tool", tool=body.name, tenant_id=tid):
        res = execute_tool(body.name, body.args, body.capabilities, timeout=body.timeout, tenant_id=tid)
    if res.get("status", 200) >= 400:
        raise HTTPException(res["status"], res.get("error", "error"))
    res["trace_id"] = current_trace_id()
    return res


@app.get("/v1/tools/logs")
def get_logs(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    items = LOGS[-20:]
    if x_tenant_id:
        items = [row for row in LOGS if row.get("tenant_id") == x_tenant_id][-20:]
    return {"logs": items}


@app.get("/v1/outbox")
def get_outbox(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"), tenant_id: str = "default"):
    tid = resolve_tenant(tenant_id, x_tenant_id)
    return {"tenant_id": tid, "messages": handlers.outbox_for(tid)}


@app.post("/v1/guardrails/check")
def guard_check(body: GuardCheck):
    if body.direction == "output":
        result = check_output(body.text)
    else:
        result = check_input(body.text, policy=body.policy)
    return {
        "allowed": result.allowed,
        "reason": result.reason,
        "pii": result.pii,
        "injection": result.injection,
        "redacted": result.redacted_text,
        "policy": result.policy,
        "injection_score": result.injection_score,
        "injection_source": result.injection_source,
    }


@app.post("/v1/guardrails/redact")
def guard_redact(body: RedactBody):
    redacted, findings = redact_pii(body.text)
    return {"redacted": redacted, "findings": findings}


@app.post("/v1/guardrails/wrap-demo")
def guard_wrap(body: WrapDemo):
    @wrap_llm
    def llm(prompt: str) -> str:
        return complete(prompt)

    try:
        output = llm(body.prompt, policy=body.policy)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return {"ok": True, "output": output}


@app.post("/v1/agent/execute")
def agent_execute(body: AgentExec, x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    tid = resolve_tenant(body.tenant_id, x_tenant_id)
    in_guard = check_input(body.input, policy=body.policy)
    if not in_guard.allowed:
        raise HTTPException(403, f"input blocked: {in_guard.reason}")

    request = body.tool_request
    planned = False
    if request is None:
        guessed = plan_tool(in_guard.redacted_text)
        if guessed:
            request = ToolRequest(**guessed)
            planned = True

    try:
        plan_text = complete(
            f"User: {in_guard.redacted_text}\nTool plan: {request.model_dump() if request else 'none'}"
        )
    except LLMError as exc:
        raise HTTPException(502, f"llm failed: {exc}") from exc

    if not request:
        return {
            "tenant_id": tid,
            "input_guard": {"allowed": in_guard.allowed, "redacted": in_guard.redacted_text},
            "planned": planned,
            "answer": check_output(plan_text).redacted_text,
            "trace_id": current_trace_id(),
        }

    with span("agent.execute", tool=request.name, tenant_id=tid):
        tres = execute_tool(request.name, request.args, body.capabilities, tenant_id=tid)
    if tres.get("status", 200) >= 400:
        raise HTTPException(tres["status"], tres.get("error"))

    result_text = tres.get("result")
    if not isinstance(result_text, str):
        result_text = str(result_text)
    out_guard = check_output(result_text)
    if not out_guard.allowed:
        raise HTTPException(403, f"output blocked: {out_guard.reason}")

    try:
        answer = complete(
            f"User asked: {in_guard.redacted_text}\nTool {request.name} returned: {out_guard.redacted_text}\nReply briefly."
        )
    except LLMError as exc:
        raise HTTPException(502, f"llm failed: {exc}") from exc
    final = check_output(answer)
    return {
        "tenant_id": tid,
        "input_guard": {"allowed": in_guard.allowed, "redacted": in_guard.redacted_text},
        "planned": planned,
        "tool_result": tres,
        "output_guard": {"allowed": out_guard.allowed, "redacted": out_guard.redacted_text},
        "answer": final.redacted_text,
        "trace_id": current_trace_id() or tres.get("trace_id"),
    }


@app.get("/", response_class=HTMLResponse)
def dash():
    return DASHBOARD.read_text(encoding="utf-8")

"""AgentRuntime FastAPI — ToolMesh + GuardRail middleware."""
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time

from ..tools.registry import register_tool, list_tools, execute_tool, grant, TOOLS, LOGS
from ..guardrails.middleware import check_input, check_output, redact_pii, detect_pii, detect_injection
from ..observability.otel import init_tracing, span, current_trace_id

init_tracing("agentruntime")
app = FastAPI(title="AgentRuntime", version="1.0.0", description="ToolMesh + GuardRail — typed tools, sandboxed, permissioned, guarded")

@app.get("/health")
def health(): return {"status":"ok","service":"agentruntime","tools":len(TOOLS)}

# ----- tools -----
class ToolRegister(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    allowed_capabilities: List[str] = []

@app.post("/v1/tools/register")
def post_register(body: ToolRegister):
    # handler stub for dynamic register
    def handler(**kwargs): return f"dynamic tool {body.name} called with {kwargs}"
    try:
        t = register_tool(body.name, body.description, body.parameters, handler, body.allowed_capabilities)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"tool": {"name": t["name"], "description": t["description"]}}

@app.get("/v1/tools")
def get_tools(q: Optional[str] = None):
    return {"tools": list_tools(q)}

class ToolExec(BaseModel):
    name: str
    args: Dict[str, Any] = {}
    capabilities: List[str] = []

class GrantBody(BaseModel):
    capabilities: List[str]
    tenant_id: str = "default"


@app.post("/v1/grants")
def post_grants(body: GrantBody, x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    tid = x_tenant_id or body.tenant_id
    return {"tenant_id": tid, "capabilities": grant(tid, body.capabilities)}


@app.post("/v1/tools/execute")
def post_execute(body: ToolExec, x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    tid = x_tenant_id or "default"
    with span("agent.tool", tool=body.name, tenant_id=tid):
        res = execute_tool(body.name, body.args, body.capabilities, tenant_id=tid)
    if res.get("status", 200) >= 400:
        raise HTTPException(res["status"], res.get("error","error"))
    res["trace_id"] = current_trace_id()
    return res

@app.get("/v1/tools/logs")
def get_logs(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    items = LOGS[-20:]
    if x_tenant_id:
        items = [l for l in LOGS if l.get("tenant_id") == x_tenant_id][-20:]
    return {"logs": items}

# ----- guardrails -----
class GuardCheck(BaseModel):
    text: str
    policy: str = "block"  # block|flag|transform
    direction: str = "input"  # input|output

@app.post("/v1/guardrails/check")
def guard_check(body: GuardCheck):
    if body.direction == "output":
        r = check_output(body.text)
    else:
        r = check_input(body.text, policy=body.policy)
    return {"allowed": r.allowed, "reason": r.reason, "pii": r.pii, "injection": r.injection, "redacted": r.redacted_text}

@app.post("/v1/guardrails/redact")
def guard_redact(body: Dict[str, Any]):
    text = body.get("text","")
    redacted, findings = redact_pii(text)
    return {"redacted": redacted, "findings": findings}

# E2E: LLM -> tool -> guard
@app.post("/v1/agent/execute")
def agent_execute(body: Dict[str, Any]):
    # body: {input: str, tool_request: {name, args}, capabilities: []}
    inp = body.get("input","")
    treq = body.get("tool_request")
    caps = body.get("capabilities", [])
    policy = body.get("policy","block")
    # 1. input guard
    in_guard = check_input(inp, policy=policy)
    if not in_guard.allowed:
        raise HTTPException(403, f"input blocked: {in_guard.reason}")
    # 2. tool exec
    if treq:
        tres = execute_tool(treq.get("name",""), treq.get("args",{}), caps)
        if tres.get("status",200) >= 400:
            raise HTTPException(tres["status"], tres.get("error"))
        result_text = str(tres.get("result",""))
        # 3. output guard
        out_guard = check_output(result_text)
        return {"input_guard": {"allowed": in_guard.allowed, "redacted": in_guard.redacted_text}, "tool_result": tres, "output_guard": {"allowed": out_guard.allowed, "redacted": out_guard.redacted_text}}
    return {"input_guard": {"allowed": in_guard.allowed, "redacted": in_guard.redacted_text}}

@app.get("/", response_class=HTMLResponse)
def dash():
    return """<!doctype html><html><head><title>AgentRuntime</title>
    <style>body{font-family:sans-serif;max-width:920px;margin:32px auto;padding:0 20px}
    .card{border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0} pre{background:#f6f6f6;padding:10px;white-space:pre-wrap}</style></head>
    <body><h1>AgentRuntime</h1>
    <p>ToolMesh (typed, permissioned, sandboxed) + GuardRail (PII, injection, policy)</p>
    <div class="card"><h3>Registered tools</h3><pre id="tools">loading…</pre></div>
    <p><a href="/docs">Swagger</a> · <a href="/health">/health</a> · <a href="/v1/tools">/v1/tools</a></p>
    <script>fetch('/v1/tools').then(r=>r.json()).then(j=>{document.getElementById('tools').textContent=j.tools.map(t=>t.name).join('\\n');});</script>
    </body></html>"""

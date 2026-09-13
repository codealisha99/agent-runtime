"""ToolMesh registry — typed schemas, discovery, permissions, sandbox."""
import os, time, uuid, json, re
from typing import Dict, Any, List, Optional, Callable

TOOLS: Dict[str, Dict[str, Any]] = {}
LOGS: List[Dict[str, Any]] = []

def register_tool(name: str, description: str, parameters: Dict[str, Any], handler: Callable, allowed_capabilities: List[str] = None, timeout: int = 5):
    if name in TOOLS:
        raise ValueError(f"tool {name} already registered")
    # validate schema shape
    if not re.match(r"^[a-z_]+$", name):
        raise ValueError("tool name must be lowercase with underscores")
    TOOLS[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,  # JSON schema
        "handler": handler,
        "allowed_capabilities": allowed_capabilities or [],
        "timeout": timeout,
        "created_at": time.time(),
    }
    return TOOLS[name]

def list_tools(query: Optional[str] = None) -> List[Dict[str, Any]]:
    items = [{"name": t["name"], "description": t["description"], "parameters": t["parameters"], "allowed_capabilities": t["allowed_capabilities"]} for t in TOOLS.values()]
    if query:
        q = query.lower()
        items = [i for i in items if q in i["name"] or q in i["description"].lower()]
    return items

def validate_args(tool: Dict[str, Any], args: Dict[str, Any]) -> Optional[str]:
    schema = tool["parameters"]
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for r in required:
        if r not in args:
            return f"missing required param: {r}"
    for k, v in args.items():
        if k not in props:
            return f"unknown param: {k}"
        exp = props[k].get("type")
        if exp == "string" and not isinstance(v, str):
            return f"param {k} must be string"
        if exp == "integer" and not isinstance(v, int):
            return f"param {k} must be integer"
        if exp == "number" and not isinstance(v, (int, float)):
            return f"param {k} must be number"
        if exp == "boolean" and not isinstance(v, bool):
            return f"param {k} must be boolean"
    return None

def check_permission(tool: Dict[str, Any], requester_capabilities: List[str]) -> bool:
    needed = set(tool["allowed_capabilities"])
    # if tool needs no capabilities, anyone can call
    if not needed:
        return True
    # requester must have all required capabilities (stub: always require explicit grant)
    # For demo, we allow if requester has at least one of needed, but ideally exact
    # We'll enforce: must have every needed capability
    return needed.issubset(set(requester_capabilities))

GRANTS: Dict[str, List[str]] = {}


def _redis():
    if os.getenv("CACHE_BACKEND", "auto") == "memory" or not os.getenv("REDIS_URL"):
        return None
    try:
        import redis
        c = redis.from_url(os.environ["REDIS_URL"])
        c.ping()
        return c
    except Exception:
        return None


def persist() -> None:
    r = _redis()
    if r is None:
        return
    r.set("agent:grants", json.dumps(GRANTS))


def hydrate() -> None:
    r = _redis()
    if r is None:
        return
    raw = r.get("agent:grants")
    if not raw:
        return
    GRANTS.clear()
    GRANTS.update(json.loads(raw))


def grant(tenant_id: str, capabilities: List[str]) -> List[str]:
    GRANTS[tenant_id] = sorted(set(GRANTS.get(tenant_id, []) + capabilities))
    persist()
    return GRANTS[tenant_id]


def capabilities_for(tenant_id: str, requester_capabilities: List[str] | None) -> List[str]:
    granted = GRANTS.get(tenant_id, [])
    # Server grants win. Body caps are ignored unless no grant row exists (test/dev bootstrap).
    if tenant_id in GRANTS:
        return granted
    return requester_capabilities or []


def _run_sandboxed_python(code: str, timeout: int = 2) -> str:
    import subprocess
    import sys
    import tempfile

    banned = ["import os", "import sys", "subprocess", "open(", "__import__", "eval("]
    low = code.lower()
    if any(b in low for b in banned):
        raise PermissionError("sandbox denied: capability escape")
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp,
            timeout=timeout,
            capture_output=True,
            text=True,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[:200] or "sandbox error")
    return (proc.stdout or "ok").strip()


def execute_tool(name: str, args: Dict[str, Any], requester_capabilities: List[str] = None, timeout: int = None, tenant_id: str = "default") -> Dict[str, Any]:
    requester_capabilities = capabilities_for(tenant_id, requester_capabilities)
    if name not in TOOLS:
        return {"error": f"tool {name} not found", "status": 404}
    tool = TOOLS[name]
    err = validate_args(tool, args)
    if err:
        return {"error": err, "status": 400}
    if tool["allowed_capabilities"] and not check_permission(tool, requester_capabilities):
        return {"error": f"permission denied for tool {name}: requires {tool['allowed_capabilities']}", "status": 403}
    tries = 2
    last = None
    for attempt in range(tries):
        try:
            if name == "run_python":
                result = _run_sandboxed_python(args["code"], timeout or tool.get("timeout", 2))
            else:
                result = tool["handler"](**args)
            LOGS.append({"tool": name, "args": args, "result": result, "ts": time.time(), "capabilities": requester_capabilities, "tenant_id": tenant_id})
            return {"result": result, "status": 200, "retries": attempt}
        except Exception as e:
            last = str(e)
    return {"error": last, "status": 500}

def clear():
    TOOLS.clear()
    LOGS.clear()
    GRANTS.clear()

# Pre-register 10 demo tools
def _init_demo():
    clear()
    register_tool("search_web", "Search the web", {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}, lambda query: f"Results for {query}: [doc1, doc2]", ["network"])
    register_tool("read_file", "Read a file", {"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}, lambda path: f"content of {path}", ["filesystem"])
    register_tool("write_file", "Write a file", {"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}, lambda path, content: f"wrote to {path}", ["filesystem"])
    register_tool("run_python", "Execute Python code", {"type":"object","properties":{"code":{"type":"string"}},"required":["code"]}, lambda code: _run_sandboxed_python(code), ["sandbox"])
    register_tool("query_db", "Query database", {"type":"object","properties":{"sql":{"type":"string"}},"required":["sql"]}, lambda sql: f"rows for {sql}", ["database"])
    register_tool("send_email", "Send email", {"type":"object","properties":{"to":{"type":"string"},"subject":{"type":"string"}},"required":["to","subject"]}, lambda to, subject: f"email to {to}", ["network"])
    register_tool("get_weather", "Get weather", {"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}, lambda city: f"weather in {city}: sunny", ["network"])
    register_tool("calc", "Calculator", {"type":"object","properties":{"expression":{"type":"string"}},"required":["expression"]}, lambda expression: str(eval(expression, {"__builtins__":{}})) if re.match(r"^[0-9+\-*/(). ]+$", expression) else "invalid", [])
    register_tool("translate", "Translate text", {"type":"object","properties":{"text":{"type":"string"},"target":{"type":"string"}},"required":["text","target"]}, lambda text, target: f"[{target}] {text}", ["network"])
    register_tool("summarize", "Summarize document", {"type":"object","properties":{"doc_id":{"type":"string"}},"required":["doc_id"]}, lambda doc_id: f"summary of {doc_id}", [])

_init_demo()
hydrate()

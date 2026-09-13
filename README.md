# AgentRuntime

**Port:** 8004  
**Folder:** `04-agent-runtime/`  
**Original PRDs:** 10 ToolMesh · 14 GuardRail  
**Acceptance:** A1–A11

Typed tools with server-side grants and a sandbox. Guardrails on input and output (PII, injection, policy). `wrap_llm()` is a reusable wrapper around any LLM call.

## Install

Python **3.11+**. Do not copy `node_modules`, `.venv`, or `__pycache__` — recreate them here.

```bash
cd 04-agent-runtime
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run locally (mock, no Docker)

```bash
cd 04-agent-runtime
source .venv/bin/activate
LLM_PROVIDER=mock CACHE_BACKEND=memory OTEL_SDK_DISABLED=true \
  uvicorn app.api.main:app --host 0.0.0.0 --port 8004 --reload
```

Open http://localhost:8004/ and `GET /health`.

## Run with Docker

From the **repo root** (not this folder):

```bash
docker compose up -d --build agentruntime
curl http://localhost:8004/health
```

## Test

```bash
cd 04-agent-runtime
source .venv/bin/activate
LLM_PROVIDER=mock CACHE_BACKEND=memory OTEL_SDK_DISABLED=true pytest -q
```


## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/tools` | List / search (`?q=`) |
| POST | `/v1/tools/register` | Dynamic tool |
| POST | `/v1/grants` | Server-side capabilities for a tenant |
| POST | `/v1/tools/execute` | Validate → permit → sandbox → run |
| GET | `/v1/tools/logs` | Tenant-filtered |
| POST | `/v1/guardrails/check` | PII + injection + policy |
| POST | `/v1/guardrails/redact` | `[REDACTED]` |
| POST | `/v1/agent/execute` | Input guard → tool → output guard |

```bash
curl -s -X POST localhost:8004/v1/tools/execute \
  -H 'content-type: application/json' \
  -d '{"name":"calc","args":{"expression":"7*6"}}'
curl -s -X POST localhost:8004/v1/guardrails/redact \
  -H 'content-type: application/json' \
  -d '{"text":"email me at a@b.com"}'
```

Pre-registered tools (10): `search_web`, `read_file`, `write_file`, `run_python`, `query_db`, `send_email`, `get_weather`, `calc`, `translate`, `summarize`.

## Honesty

Most tools are stubs. `run_python` is a real subprocess in a tempdir with a deny-list (`import os/sys`, `open(`, `eval(`). Grants persist in Redis.

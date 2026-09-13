# AgentRuntime

**Port:** 8004  
**Folder:** `04-agent-runtime/`  
**Original PRDs:** 10 ToolMesh · 14 GuardRail  
**Acceptance:** A1–A11

A runtime where an agent can only call typed, granted, sandboxed tools. Every hop is wrapped in PII, injection, and policy checks. `wrap_llm()` is a reusable wrapper around any LLM call.

## Install

Python **3.11+** (3.11 or 3.12; pinned `pydantic==2.7.0` does not build on 3.14). Do not copy `node_modules`, `.venv`, or `__pycache__` — recreate them here.

```bash
cd 04-agent-runtime
python3.11 -m venv .venv
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
| POST | `/v1/grants` | Replace server-side capabilities for a tenant |
| GET | `/v1/grants` | Current tenant grant row |
| POST | `/v1/tools/execute` | Validate → permit → sandbox → run |
| GET | `/v1/tools/logs` | Tenant-filtered |
| GET | `/v1/outbox` | Queued mail for the tenant |
| POST | `/v1/guardrails/check` | PII + injection + policy |
| POST | `/v1/guardrails/redact` | `[REDACTED]` |
| POST | `/v1/guardrails/wrap-demo` | `wrap_llm` around the mock LLM |
| POST | `/v1/agent/execute` | Input guard → LLM plan → tool → output guard |

```bash
curl -s -X POST localhost:8004/v1/tools/execute \
  -H 'content-type: application/json' \
  -d '{"name":"calc","args":{"expression":"7*6"}}'
curl -s -X POST localhost:8004/v1/guardrails/redact \
  -H 'content-type: application/json' \
  -d '{"text":"email me at a@b.com"}'
```

Pre-registered tools (10): `search_web`, `read_file`, `write_file`, `run_python`, `query_db`, `send_email`, `get_weather`, `calc`, `translate`, `summarize`.

## What is real

- `read_file` / `write_file` operate on a per-tenant workspace (`WORKSPACE_DIR`). Path escape is 403.
- `run_python` is AST-checked, then run with `python -I` in a tempdir. `os` / `sys` / `open` / `eval` / network modules are denied. Timeouts return 408.
- `query_db` is read-only SQLite (`SELECT` only) with a seeded catalog.
- `send_email` validates the address and queues to `/v1/outbox` (no SMTP).
- `search_web`, `get_weather`, `translate`, `summarize` use a built-in corpus / phrasebook so the service works without API keys.
- `calc` is a safe AST evaluator, not `eval`.
- Grants persist in Redis when `CACHE_BACKEND` is not `memory`.
- `POST /v1/agent/execute` always honors `X-Tenant-Id`. If no `tool_request` is sent, the mock planner can pick `calc`, `get_weather`, `translate`, `search_web`, or `summarize`.

## Env

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `mock` | `mock` \| `openai` \| `ollama` |
| `CACHE_BACKEND` | `auto` | `memory` skips Redis |
| `REDIS_URL` | — | Grant persistence |
| `WORKSPACE_DIR` | `data/workspace` | Tenant files + SQLite |
| `TOOL_TIMEOUT` | `5` | Seconds |
| `SANDBOX_TIMEOUT` | `2` | `run_python` seconds |
| `OTEL_SDK_DISABLED` | — | Set `true` to skip tracing |

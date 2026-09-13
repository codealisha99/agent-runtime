"""Real tool handlers. Filesystem and SQLite stay inside the tenant workspace."""
from __future__ import annotations

import ast
import json
import operator
import re
import sqlite3
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..integrations import mail as mail_svc
from ..integrations import search as search_svc
from ..integrations import translate as translate_svc
from ..integrations import weather as weather_svc
from .catalog import CORPUS
from .sandbox import run_sandboxed_python

_tenant: ContextVar[str] = ContextVar("tenant_id", default="default")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
SQL_WRITE = re.compile(
    r"\b(drop|delete|attach|detach|pragma|update|insert|alter|create|replace|vacuum|copy)\b",
    re.I,
)

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

EMAIL_OUTBOX: list[dict[str, Any]] = []


def set_tenant(tenant_id: str):
    return _tenant.set(tenant_id or "default")


def reset_tenant(token) -> None:
    _tenant.reset(token)


def current_tenant() -> str:
    return _tenant.get() or "default"


def workspace_root(tenant_id: str | None = None) -> Path:
    settings = get_settings()
    base = Path(settings.workspace_dir or "data/workspace").resolve()
    root = (base / (tenant_id or current_tenant())).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_path(rel: str, tenant_id: str | None = None) -> Path:
    raw = (rel or "").strip()
    if not raw or raw.startswith("/") or raw.startswith("~"):
        raise PermissionError("path escapes workspace")
    parts = Path(raw).parts
    if any(p in {"..", ""} for p in parts):
        raise PermissionError("path escapes workspace")
    root = workspace_root(tenant_id)
    full = (root / raw).resolve()
    if not str(full).startswith(str(root)):
        raise PermissionError("path escapes workspace")
    return full


def _db_path(tenant_id: str | None = None) -> Path:
    return workspace_root(tenant_id) / "catalog.db"


def seed_db(tenant_id: str | None = None) -> Path:
    path = _db_path(tenant_id)
    if path.exists():
        return path
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                category TEXT NOT NULL
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                city TEXT NOT NULL
            );
            INSERT INTO products VALUES
                (1, 'AgentRuntime license', 49.0, 'software'),
                (2, 'GuardRail add-on', 19.0, 'software'),
                (3, 'On-call review', 240.0, 'services');
            INSERT INTO orders VALUES
                (1, 1, 3, 'San Francisco'),
                (2, 2, 8, 'Berlin'),
                (3, 3, 1, 'Mumbai');
            """
        )
        conn.commit()
    finally:
        conn.close()
    return path


def search_web(query: str) -> dict[str, Any]:
    return search_svc.search_web(query)


def read_file(path: str) -> dict[str, Any]:
    target = safe_path(path)
    if not target.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    text = target.read_text(encoding="utf-8")
    return {"path": path, "content": text, "bytes": len(text.encode("utf-8"))}


def write_file(path: str, content: str) -> dict[str, Any]:
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "bytes": len(content.encode("utf-8")), "written": True}


def run_python(code: str) -> str:
    return run_sandboxed_python(code, timeout=get_settings().sandbox_timeout)


def query_db(sql: str) -> dict[str, Any]:
    statement = sql.strip().rstrip(";")
    if not statement:
        raise ValueError("sql must not be empty")
    if not re.match(r"^select\b", statement, re.I) or SQL_WRITE.search(statement):
        raise PermissionError("only SELECT is allowed")
    path = seed_db()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(statement)
        rows = [dict(r) for r in cur.fetchmany(50)]
        return {"sql": statement, "rows": rows, "count": len(rows)}
    finally:
        conn.close()


def send_email(to: str, subject: str, body: str = "") -> dict[str, Any]:
    if not EMAIL_RE.match(to):
        raise ValueError("invalid email address")
    delivery = mail_svc.deliver(to, subject, body)
    item = {
        "id": str(uuid.uuid4()),
        "to": to,
        "subject": subject,
        "body": body,
        "tenant_id": current_tenant(),
        "ts": time.time(),
        "status": delivery["status"],
        "transport": delivery.get("transport"),
    }
    EMAIL_OUTBOX.append(item)
    return {"message_id": item["id"], "to": to, **delivery}


def get_weather(city: str) -> dict[str, Any]:
    return weather_svc.get_weather(city)


def _eval_ast(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_ast(node.left), _eval_ast(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_ast(node.operand))
    raise ValueError("invalid expression")


def calc(expression: str) -> str:
    if not re.match(r"^[0-9+\-*/(). %]+$", expression or ""):
        raise ValueError("invalid expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid expression") from exc
    value = _eval_ast(tree)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def translate(text: str, target: str) -> dict[str, Any]:
    return translate_svc.translate(text, target)


def summarize(doc_id: str) -> dict[str, Any]:
    text = ""
    source = "missing"
    if doc_id in CORPUS:
        text = CORPUS[doc_id]["text"]
        source = "corpus"
    else:
        try:
            target = safe_path(doc_id)
            if target.is_file():
                text = target.read_text(encoding="utf-8")
                source = "workspace"
        except PermissionError:
            text = ""
    if not text:
        raise FileNotFoundError(f"document not found: {doc_id}")
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    summary = " ".join(sentences[:2])[:320]
    return {"doc_id": doc_id, "summary": summary, "source": source, "chars": len(text)}


def outbox_for(tenant_id: str) -> list[dict[str, Any]]:
    return [m for m in EMAIL_OUTBOX if m.get("tenant_id") == tenant_id][-20:]

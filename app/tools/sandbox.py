"""Restricted Python execution: AST deny-list + isolated subprocess."""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from typing import Final

ALLOWED_MODULES: Final[frozenset[str]] = frozenset(
    {
        "math",
        "json",
        "statistics",
        "datetime",
        "re",
        "time",
        "random",
        "decimal",
        "collections",
        "itertools",
        "functools",
        "string",
        "textwrap",
        "hashlib",
        "base64",
        "unicodedata",
    }
)

FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "pathlib",
        "shutil",
        "ctypes",
        "multiprocessing",
        "importlib",
        "builtins",
        "eval",
        "exec",
        "compile",
        "open",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "input",
        "exit",
        "quit",
        "help",
        "memoryview",
    }
)


class _SandboxGuard(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in ALLOWED_MODULES:
                raise PermissionError(f"sandbox denied: import {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        top = (node.module or "").split(".")[0]
        if top not in ALLOWED_MODULES:
            raise PermissionError(f"sandbox denied: import {node.module}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
            raise PermissionError(f"sandbox denied: name {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise PermissionError("sandbox denied: private attribute")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAMES:
            raise PermissionError(f"sandbox denied: call {func.id}")
        self.generic_visit(node)


def validate_code(code: str) -> None:
    if not code or not code.strip():
        raise ValueError("code must not be empty")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"syntax error: {exc.msg}") from exc
    _SandboxGuard().visit(tree)


def run_sandboxed_python(code: str, timeout: int = 2) -> str:
    validate_code(code)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=tmp,
                timeout=timeout,
                capture_output=True,
                text=True,
                env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONSAFEPATH": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("tool timed out") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "sandbox error").strip()
        raise RuntimeError(err[:240])
    return (proc.stdout or "ok").strip()

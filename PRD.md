# PRD — AgentRuntime (04-agent-runtime)

## Problem

LLM tool-calling without schemas, permissions, or sandboxing is a security incident waiting to happen.

## Objective

A runtime where an agent can only call typed, granted, sandboxed tools, and every LLM hop is wrapped in PII / injection / policy checks.

## Functional requirements

1. ≥10 tools with JSON Schema parameters.
2. Invalid args → 400; missing capability → 403.
3. Server grants win over body `capabilities` once a grant row exists.
4. `run_python` has no implicit filesystem / shell / network.
5. 50-case PII suite: emails become `[REDACTED]`.
6. Injection (“Ignore previous instructions…”) honor block / flag / transform.
7. `wrap_llm(fn)` applies the same policy to any callable.

## Out of scope

Production WAF, fine-tuned injection classifiers, a tool marketplace UI.

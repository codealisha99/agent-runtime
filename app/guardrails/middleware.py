"""GuardRail middleware — PII, injection, policy, wrap_llm."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import get_settings
from .classifier import get_classifier

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{12,}\b")
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|your)\s+instructions",
    r"ignore\s+the\s+above",
    r"system\s*:\s*you\s+are",
    r"jailbreak",
    r"disregard\s+all\s+prior",
    r"disregard\s+(previous|all)\s+(instructions|rules)",
    r"do\s+anything\s+now",
    r"\bdan\s+mode\b",
    r"developer\s+mode",
    r"pretend\s+to\s+be",
    r"you\s+are\s+now\b",
    r"override\s+safety",
    r"bypass\s+(the\s+)?(filter|guard|policy|safety)",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"new\s+instructions\s*:",
    r"admin\s+override",
    r"sudo\s+mode",
    r"unfiltered\s+response",
    r"forget\s+(all\s+)?(previous|prior)\s+(rules|instructions)",
    r"act\s+as\s+(if\s+you\s+have\s+no\s+restrictions|DAN)",
]

POLICY_BLOCKED = [
    "hack the system",
    "illegal instructions",
    "how to make a bomb",
    "build a bomb",
    "credit card dump",
]


@dataclass
class GuardResult:
    allowed: bool
    reason: str
    pii: list[dict[str, Any]]
    injection: bool
    redacted_text: str
    policy: str = "block"
    injection_score: float = 0.0
    injection_source: str = ""


def detect_pii(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for kind, pattern in (
        ("email", EMAIL_RE),
        ("ssn", SSN_RE),
        ("api_key", API_KEY_RE),
        ("aws_key", AWS_KEY_RE),
        ("phone", PHONE_RE),
        ("card", CARD_RE),
    ):
        for match in pattern.finditer(text):
            value = match.group(0)
            if kind == "phone" and len(re.sub(r"\D", "", value)) < 10:
                continue
            if kind == "card":
                digits = re.sub(r"\D", "", value)
                if len(digits) < 13 or SSN_RE.fullmatch(value.strip()):
                    continue
            findings.append({"type": kind, "value": value, "span": match.span()})
    return findings


def redact_pii(text: str) -> tuple[str, list[dict[str, Any]]]:
    findings = detect_pii(text)
    redacted = API_KEY_RE.sub("[REDACTED]", text)
    redacted = AWS_KEY_RE.sub("[REDACTED]", redacted)
    redacted = EMAIL_RE.sub("[REDACTED]", redacted)
    redacted = SSN_RE.sub("[REDACTED]", redacted)
    redacted = CARD_RE.sub("[REDACTED]", redacted)
    redacted = PHONE_RE.sub("[REDACTED]", redacted)
    return redacted, findings


def detect_injection(text: str) -> tuple[bool, str, float]:
    low = text.lower()
    score = get_classifier().score(text)
    for pat in INJECTION_PATTERNS:
        if re.search(pat, low):
            return True, f"regex:{pat}", max(score, 0.99)
    threshold = get_settings().injection_threshold
    if score >= threshold:
        return True, f"classifier:{score:.2f}", score
    return False, "", score


def neutralize_injection(text: str, detail: str) -> str:
    if detail.startswith("regex:"):
        pat = detail.split(":", 1)[1]
        return re.sub(pat, "[REMOVED]", text, flags=re.I)
    stripped = re.sub(
        r"(system prompt|jailbreak|dan mode|developer mode|sudo mode|unfiltered|hidden prompt)",
        "[REMOVED]",
        text,
        flags=re.I,
    )
    if stripped != text:
        return stripped
    return f"[REMOVED] {text}"


def policy_check(text: str) -> tuple[bool, str]:
    low = text.lower()
    for phrase in POLICY_BLOCKED:
        if phrase in low:
            return False, f"policy violation: {phrase}"
    return True, ""


def check_input(text: str, policy: str = "block") -> GuardResult:
    pii = detect_pii(text)
    injection, detail, score = detect_injection(text)
    allowed_policy, policy_reason = policy_check(text)
    allowed = True
    reason_out = "ok"
    working = text
    if injection:
        if policy == "block":
            allowed = False
            reason_out = f"injection detected: {detail}"
        elif policy == "flag":
            reason_out = f"injection flagged: {detail}"
        elif policy == "transform":
            working = neutralize_injection(working, detail)
            reason_out = f"injection transformed: {detail}"
        else:
            allowed = False
            reason_out = f"unknown policy: {policy}"
    if not allowed_policy:
        allowed = False
        reason_out = policy_reason
    redacted, _ = redact_pii(working)
    source = detail.split(":", 1)[0] if detail else ""
    return GuardResult(allowed, reason_out, pii, injection, redacted, policy, score, source)


def check_output(text: str) -> GuardResult:
    pii = detect_pii(text)
    redacted, _ = redact_pii(text)
    allowed_policy, reason = policy_check(text)
    injection, detail, score = detect_injection(text)
    source = detail.split(":", 1)[0] if detail else ""
    if not allowed_policy:
        return GuardResult(False, reason, pii, injection, redacted, "block", score, source)
    if injection:
        return GuardResult(False, f"injection detected: {detail}", pii, True, redacted, "block", score, source)
    return GuardResult(True, "ok", pii, False, redacted, "block", score, source)


def wrap_llm(fn):
    def inner(prompt: str, policy: str = "block"):
        guarded = check_input(prompt, policy=policy)
        if not guarded.allowed:
            raise PermissionError(guarded.reason)
        out = fn(guarded.redacted_text)
        guarded_out = check_output(str(out))
        if not guarded_out.allowed:
            raise PermissionError(guarded_out.reason)
        return guarded_out.redacted_text

    return inner

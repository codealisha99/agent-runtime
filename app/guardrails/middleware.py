"""GuardRail middleware — PII, injection, policy, content filtering."""
import re
from typing import Dict, Any, List, Tuple

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
INJECTION_PATTERNS = [
    r"ignore\s+previous\s+instructions",
    r"system\s*:\s*you\s+are",
    r"jailbreak",
    r"disregard\s+all\s+prior",
    r"do\s+anything\s+now",
]

def detect_pii(text: str) -> List[Dict[str, str]]:
    findings = []
    for m in EMAIL_RE.finditer(text):
        findings.append({"type": "email", "value": m.group(0), "span": m.span()})
    for m in PHONE_RE.finditer(text):
        # avoid matching short numbers that are not phones
        if len(re.sub(r"\D","",m.group(0))) >= 10:
            findings.append({"type": "phone", "value": m.group(0), "span": m.span()})
    for m in SSN_RE.finditer(text):
        findings.append({"type": "ssn", "value": m.group(0), "span": m.span()})
    return findings

def redact_pii(text: str) -> Tuple[str, List[Dict]]:
    findings = detect_pii(text)
    redacted = text
    redacted = EMAIL_RE.sub("[REDACTED]", redacted)
    redacted = PHONE_RE.sub("[REDACTED]", redacted)
    redacted = SSN_RE.sub("[REDACTED]", redacted)
    return redacted, findings

def detect_injection(text: str) -> Tuple[bool, str]:
    low = text.lower()
    for pat in INJECTION_PATTERNS:
        if re.search(pat, low):
            return True, pat
    return False, ""

def policy_check(text: str) -> Tuple[bool, str]:
    # simple policy: disallow disallowed content
    blocked = ["hack the system", "illegal instructions", "how to make a bomb"]
    low = text.lower()
    for b in blocked:
        if b in low:
            return False, f"policy violation: {b}"
    return True, ""

def content_filter(text: str) -> Tuple[bool, str]:
    # same as policy for demo
    return policy_check(text)

class GuardResult:
    def __init__(self, allowed: bool, reason: str, pii: List[Dict], injection: bool, redacted_text: str):
        self.allowed = allowed
        self.reason = reason
        self.pii = pii
        self.injection = injection
        self.redacted_text = redacted_text

def check_input(text: str, policy: str = "block") -> GuardResult:
    pii = detect_pii(text)
    injection, pat = detect_injection(text)
    allowed_policy, reason = policy_check(text)
    allowed_filter, _ = content_filter(text)
    allowed = True
    reason_out = "ok"
    if injection:
        if policy == "block":
            allowed = False
            reason_out = f"injection detected: {pat}"
        elif policy == "flag":
            reason_out = f"injection flagged: {pat}"
        elif policy == "transform":
            text = re.sub(pat, "[REMOVED]", text, flags=re.I)
            reason_out = f"injection transformed: {pat}"
    if not allowed_policy:
        allowed = False
        reason_out = reason
    if not allowed_filter:
        allowed = False
        reason_out = "content filtered"
    redacted, _ = redact_pii(text)
    return GuardResult(allowed, reason_out, pii, injection, redacted)

def wrap_llm(fn):
    def inner(prompt: str, policy: str = "block"):
        guarded = check_input(prompt, policy=policy)
        if not guarded.allowed:
            raise PermissionError(guarded.reason)
        out = fn(guarded.redacted_text)
        return check_output(str(out)).redacted_text
    return inner


def check_output(text: str) -> GuardResult:
    pii = detect_pii(text)
    redacted, _ = redact_pii(text)
    allowed_policy, reason = policy_check(text)
    return GuardResult(allowed_policy, reason if not allowed_policy else "ok", pii, False, redacted)

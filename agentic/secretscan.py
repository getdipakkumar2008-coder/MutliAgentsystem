"""Secret detection and redaction. Findings never contain the secret value."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

ALLOW_MARKER = "agentic:allow-secret"

# (rule name, pattern). Ordered from most to least specific.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("anthropic-api-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai-api-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY(?: BLOCK)?-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
]
_ASSIGNMENT = re.compile(
    r"""(?ix)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|token|passw(?:or)?d|pwd)\b
        ["']?\s*[:=]\s*["'](?P<value>[^"'\s]{16,})["']""")
_PLACEHOLDER = re.compile(r"(?i)example|placeholder|changeme|change[_-]me|your[_-]|xxx|<[^>]+>|\$\{|\{\{|dummy|sample|redacted|test")


@dataclass(frozen=True)
class Finding:
    rule: str
    line: int


def _entropy(s: str) -> float:
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def _spans(line: str) -> list[tuple[str, int, int]]:
    spans = [(rule, m.start(), m.end()) for rule, pat in _PATTERNS for m in pat.finditer(line)]
    for m in _ASSIGNMENT.finditer(line):
        value = m.group("value")
        if not _PLACEHOLDER.search(value) and _entropy(value) >= 3.5:
            spans.append(("hardcoded-credential", m.start("value"), m.end("value")))
    return spans


def scan_text(text: str) -> list[Finding]:
    """Findings by rule and 1-based line number. Lines carrying the allow marker are skipped."""
    findings = []
    for n, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line:
            continue
        findings += [Finding(rule, n) for rule, _, _ in _spans(line)]
    return findings


def redact(text: str) -> str:
    """Replace every detected secret with [REDACTED:<rule>]."""
    out = []
    for line in text.split("\n"):
        pieces, pos = [], 0
        for rule, start, end in sorted(_spans(line), key=lambda s: s[1]):
            if start < pos:
                continue
            pieces += [line[pos:start], f"[REDACTED:{rule}]"]
            pos = end
        pieces.append(line[pos:])
        out.append("".join(pieces))
    return "\n".join(out)

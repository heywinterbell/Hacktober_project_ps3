"""Rule-based claim classification and extraction.

Rules first: backticked identifiers, name() patterns, semantic versions,
issue references, fenced code blocks, and "adds tests" phrases.
An optional local LLM may later *merge* improvements into this result —
it never replaces it, and any failure falls back to these rules silently.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from .models import Claim, ReportType

# --- patterns -----------------------------------------------------------------

_BACKTICK_SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")
_CALL_SYMBOL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\(\)")
_VERSION = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?)\b")
_ISSUE_LEAD = re.compile(r"\b(?:fixes|closes|resolves)\s+([^.\n]*)", re.IGNORECASE)
_ISSUE_NUM = re.compile(r"#(\d+)")
_FENCE = re.compile(r"```(?:[A-Za-z0-9_+-]*)\n(.*?)```", re.DOTALL)

_TESTS_PHRASES = (
    "adds tests",
    "adding tests",
    "add tests",
    "adds test",
    "added tests",
    "new tests",
    "test(s) included",
    "includes tests",
    "with tests",
)

_SECURITY_KEYWORDS = (
    "rce",
    "cve-",
    "injection",
    "exploit",
    "vulnerability",
    "vulnerable",
    "xss",
    "ssrf",
    "csrf",
    "remote code",
    "arbitrary code",
    "privilege escalation",
    "security issue",
    "security bug",
    "security report",
    "command injection",
    "path traversal",
    "deserialization",
)

_PR_KEYWORDS = (
    "pull request",
    "merge request",
    "this pr",
    "this merge",
    "fixes #",
    "closes #",
    "resolves #",
)

_HINT_MAP = {
    "bug": ReportType.BUG,
    "security": ReportType.SECURITY,
    "pr": ReportType.PULL_REQUEST,
    "pull_request": ReportType.PULL_REQUEST,
    "pull-request": ReportType.PULL_REQUEST,
    "pullrequest": ReportType.PULL_REQUEST,
}


# --- classify -----------------------------------------------------------------


def classify(title: str, body: str = "", kind_hint: str | None = None) -> ReportType:
    """Decide whether the input is a bug report, security report, or PR.

    A ``kind_hint`` of bug/security/pr wins outright. Otherwise security
    keywords are checked before PR keywords, defaulting to bug.
    """
    if kind_hint is not None:
        key = kind_hint.strip().lower()
        if key in _HINT_MAP:
            return _HINT_MAP[key]
        raise ValueError(f"unknown kind_hint: {kind_hint!r} (use bug, security, or pr)")

    text = f"{title}\n{body}".lower()
    if any(kw in text for kw in _SECURITY_KEYWORDS):
        return ReportType.SECURITY
    if any(kw in text for kw in _PR_KEYWORDS):
        return ReportType.PULL_REQUEST
    return ReportType.BUG


# --- extract ------------------------------------------------------------------


def split_title_body(text: str) -> tuple[str, str]:
    """First non-empty line is the title; the rest is the body."""
    lines = text.strip().splitlines()
    if not lines:
        return "", ""
    return lines[0].strip(), "\n".join(lines[1:]).strip()


def _extract_symbols(text: str) -> list[str]:
    """Backticked identifiers and name() calls, de-duplicated in order."""
    found: list[str] = []
    for match in (*_BACKTICK_SYMBOL.finditer(text), *_CALL_SYMBOL.finditer(text)):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def _extract_versions(text: str, symbols: list[str]) -> list[str]:
    """Semantic versions, skipping anything that is actually a symbol name."""
    versions: list[str] = []
    for match in _VERSION.finditer(text):
        ver = match.group(1)
        if ver in symbols or ver in versions:
            continue
        versions.append(ver)
    return versions


def _extract_issue_refs(text: str) -> list[int]:
    """All issue numbers in `fixes/closes/resolves ...` phrases, in order."""
    refs: list[int] = []
    for lead in _ISSUE_LEAD.finditer(text):
        for num in _ISSUE_NUM.finditer(lead.group(1)):
            ref = int(num.group(1))
            if ref not in refs:
                refs.append(ref)
    return refs


def extract_claim(text: str, report_type: ReportType) -> Claim:
    """Build a structured Claim from raw report text using rules only."""
    title, body = split_title_body(text)
    symbols = _extract_symbols(text)
    versions = _extract_versions(text, symbols)
    issue_refs = _extract_issue_refs(text)
    fence = _FENCE.search(text)
    repro_snippet = fence.group(1).rstrip("\n") if fence else None
    claims_tests = any(phrase in text.lower() for phrase in _TESTS_PHRASES)

    return Claim(
        type=report_type,
        raw_text=text,
        title=title,
        symbols=symbols,
        versions=versions,
        issue_refs=issue_refs,
        repro_snippet=repro_snippet,
        claims_tests=claims_tests,
    )


def merge_llm(claim: Claim, extra: dict[str, Any]) -> Claim:
    """Add already-sanitized model findings to a rule-based claim.

    Rules always win; the model can only add symbols/versions the rules missed,
    or supply a snippet/tests-claim the rules did not find.
    """
    symbols = list(claim.symbols)
    symbols += [s for s in extra.get("symbols", []) if s not in symbols]
    versions = list(claim.versions)
    versions += [v for v in extra.get("versions", []) if v not in versions]
    return dataclasses.replace(
        claim,
        symbols=symbols,
        versions=versions,
        repro_snippet=claim.repro_snippet or extra.get("repro_snippet"),
        claims_tests=claim.claims_tests or bool(extra.get("claims_tests")),
    )


def extract_from_text(
    text: str, kind_hint: str | None = None, *, use_llm: bool = False
) -> Claim:
    """Classify then extract. With ``use_llm=True`` the local model may add
    grounded details; any model failure silently leaves the rule-based claim."""
    title, body = split_title_body(text)
    report_type = classify(title, body, kind_hint)
    claim = extract_claim(text, report_type)
    if not use_llm:
        return claim
    try:
        from . import llm

        raw = llm.extract_with_llm(llm.REPORT_TO_CLAIM_TYPE[report_type], text)
        if raw is not None:
            claim = merge_llm(claim, llm.sanitize_extraction(text, raw))
    except Exception:  # noqa: BLE001 - the model is optional; never break extraction
        pass
    return claim


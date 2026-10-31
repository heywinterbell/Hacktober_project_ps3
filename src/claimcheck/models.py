"""Core data model: Claim, Evidence, Verdict, Report.

Verdicts come from real parsing and sandboxed execution, never from an LLM.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    # Backport of Python 3.11's enum.StrEnum for Python 3.10 compatibility.
    # Mirrors the stdlib implementation so str()/format()/repr() behave
    # identically on every supported interpreter.
    class StrEnum(str, Enum):
        __str__ = str.__str__
        __format__ = str.__format__


class ReportType(StrEnum):
    """Kind of maintainer input being triaged."""

    BUG = "bug"
    SECURITY = "security"
    PULL_REQUEST = "pr"


class Verdict(StrEnum):
    """Outcome of a single check, or of the whole report."""

    CONFIRMED = "confirmed"  # ✓ claim held up (e.g. reproduced)
    REFUTED = "refuted"  # ✗ claim is false (e.g. symbol does not exist)
    WARNING = "warning"  # ! something is missing (e.g. no test covers change)
    INCONCLUSIVE = "inconclusive"  # could not decide; always say why


@dataclass
class Claim:
    """Structured extraction from a raw report."""

    type: ReportType
    raw_text: str
    title: str
    symbols: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    issue_refs: list[int] = field(default_factory=list)
    repro_snippet: str | None = None
    claims_tests: bool = False


@dataclass
class Evidence:
    """One check's result, with enough detail to be verified by a human."""

    check: str  # "symbol_exists" | "version_exists" | "reproduction" | "pr_coverage"
    verdict: Verdict
    summary: str  # one line, e.g. "✗ parse_url_v2() does not exist"
    details: dict = field(default_factory=dict)
    sandboxed: bool = False


@dataclass
class Report:
    """Full triage result for one claim."""

    claim: Claim
    evidence: list[Evidence]
    overall: Verdict
    llm_summary: str | None = None  # optional, clearly labelled as model-written


def overall_verdict(evidence: list[Evidence]) -> Verdict:
    """Aggregate evidence: any REFUTED → refuted; else WARNING → warning;
    else CONFIRMED → confirmed; else inconclusive."""
    verdicts = {e.verdict for e in evidence}
    if Verdict.REFUTED in verdicts:
        return Verdict.REFUTED
    if Verdict.WARNING in verdicts:
        return Verdict.WARNING
    if Verdict.CONFIRMED in verdicts:
        return Verdict.CONFIRMED
    return Verdict.INCONCLUSIVE


def build_report(claim: Claim, evidence: list[Evidence]) -> Report:
    """Assemble a Report with the aggregated overall verdict."""
    return Report(claim=claim, evidence=evidence, overall=overall_verdict(evidence))

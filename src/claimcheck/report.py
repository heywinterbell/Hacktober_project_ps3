"""Report rendering: produce Markdown evidence for all three check types.

This module knows how to turn the evidence lists from ``check_symbols``,
``check_reproduction``, and ``check_pr_coverage`` into a single Markdown
page that can be posted as a comment on a PR.

The output format matches the slide deck expectations:
- verdict indicator: ``✓`` / ``!`` / ``✗``
- collapsible `<details>` with raw output/logs
- sandbox status line (strong / weak)
- optional model-written summary (absent in v1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceItem:
    """One evidence check result."""

    check: str
    verdict: str  # "CONFIRMED" | "WARNING" | "REFUTED" | "INCONCLUSIVE"
    summary: str
    details: str = ""
    isolation: str | None = None  # "strong" | "weak" | None


@dataclass
class Report:
    """Complete Markdown report for a single claim."""

    claim_type: str  # "symbols" | "reproduction" | "pr_coverage"
    evidence: list[EvidenceItem]
    sandboxed: bool
    # derived fields for the template
    _verdict_icons: dict[str, str] = field(
        default_factory=lambda: {
            "CONFIRMED": "✓",
            "WARNING": "!",
            "REFUTED": "✗",
            "INCONCLUSIVE": "?",
        }
    )

    # ------------------------------------------------------------------
    # Template methods
    # ------------------------------------------------------------------

    def _verdit_icon(self) -> str:
        """Return the emoji/indicator for the first (most important) verdict."""
        if not self.evidence:
            return "?"
        return self._verdict_icons.get(self.evidence[0].verdict, "?")

    def _sandbox_line(self) -> str:
        """Human-readable sandbox status."""
        if self.sandboxed is True:
            return "Isolation: **strong** (Docker)"
        if self.sandboxed is False:
            return "Isolation: **weak** (restricted subprocess)"
        return "Isolation: **unknown**"

    def _details_collapsible(self, item: EvidenceItem) -> str:
        """Render ``<details>`` block for one check's output."""
        title = f"{self._verdict_icons.get(item.verdict, '?')} {item.check}: {item.summary}"
        body = item.details if item.details else "_no additional details_"
        return f"<details><summary>{title}</summary>\n\n```\n{body}\n```\n</details>\n"

    def _evidence_block(self) -> str:
        """Render all evidence items as a concatenated block."""
        blocks: list[str] = []
        for item in self.evidence:
            blocks.append(self._details_collapsible(item))
        return "".join(blocks)

    # ------------------------------------------------------------------
    # Public rendering
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Render the full report as Markdown suitable for a PR comment."""
        icon = self._verdit_icon()
        sandbox = self._sandbox_line()

        header = f"## {self.claim_type.title()} check\n"
        header += f"**Verdict:** {icon} {self.evidence[0].verdict}  " if self.evidence else ""
        header += f"{sandbox}\n"

        # Collapsible details for each evidence item
        details = self._evidence_block()
        if not details.strip():
            details = "_no evidence items_"

        return f"{header}\n{details}\n"

    # ------------------------------------------------------------------
    # Factory: build a Report from the three check types
    # ------------------------------------------------------------------

    @staticmethod
    def from_checks(
        claim_type: str,
        *,
        symbols_evidence: list[dict[str, Any]] | None = None,
        repro_evidence: list[dict[str, Any]] | None = None,
        pr_cov_evidence: list[dict[str, Any]] | None = None,
        sandboxed: bool = True,
    ) -> Report:
        """Construct a ``Report`` from raw evidence dicts.

        Exactly one of the three evidence lists should be non‐None; the
        others are ignored.
        """
        evidence: list[EvidenceItem] = []

        if claim_type == "symbols" and symbols_evidence:
            for d in symbols_evidence:
                evidence.append(
                    EvidenceItem(
                        check=d.get("check", "unknown"),
                        verdict=d.get("verdict", "INCONCLUSIVE"),
                        summary=d.get("summary", ""),
                        details=d.get("details", ""),
                        isolation=d.get("isolation"),
                    )
                )
        elif claim_type == "reproduction" and repro_evidence:
            for d in repro_evidence:
                evidence.append(
                    EvidenceItem(
                        check=d.get("check", "unknown"),
                        verdict=d.get("verdict", "INCONCLUSIVE"),
                        summary=d.get("summary", ""),
                        details=d.get("details", ""),
                        isolation=d.get("isolation"),
                    )
                )
        elif claim_type == "pr_coverage" and pr_cov_evidence:
            for d in pr_cov_evidence:
                evidence.append(
                    EvidenceItem(
                        check=d.get("check", "unknown"),
                        verdict=d.get("verdict", "INCONCLUSIVE"),
                        summary=d.get("summary", ""),
                        details=d.get("details", ""),
                        isolation=d.get("isolation"),
                    )
                )
        else:
            # Fallback: empty evidence
            evidence.append(
                EvidenceItem(
                    check="unknown",
                    verdict="INCONCLUSIVE",
                    summary="no check results available",
                    details="",
                    isolation=None,
                )
            )

        return Report(claim_type=claim_type, evidence=evidence, sandboxed=sandboxed)


# ---------------------------------------------------------------------------
# CLI helper (wired to ``claimcheck`` command)
# ---------------------------------------------------------------------------

def run_report(
    claim_type: str,
    *,
    symbols_evidence: list[dict[str, Any]] | None = None,
    repro_evidence: list[dict[str, Any]] | None = None,
    pr_cov_evidence: list[dict[str, Any]] | None = None,
    sandboxed: bool = True,
) -> str:
    """Convenience wrapper that returns the Markdown string for a given claim type."""
    report = Report.from_checks(
        claim_type,
        symbols_evidence=symbols_evidence,
        repro_evidence=repro_evidence,
        pr_cov_evidence=pr_cov_evidence,
        sandboxed=sandboxed,
    )
    return report.to_markdown()
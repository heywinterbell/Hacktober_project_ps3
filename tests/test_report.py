"""Tests for ``src/claimcheck/report.py`` — Markdown evidence rendering."""

from __future__ import annotations

from claimcheck.report import EvidenceItem, Report, run_report


# ---------------------------------------------------------------------------
# EvidenceItem / Report primitives
# ---------------------------------------------------------------------------
def test_evidence_item_defaults():
    item = EvidenceItem(check="symbol_exists", verdict="CONFIRMED", summary="ok")
    assert item.details == ""
    assert item.isolation is None


def test_report_verdict_icon_empty_evidence():
    report = Report(claim_type="symbols", evidence=[], sandboxed=False)
    assert report._verdit_icon() == "?"
    assert "_no evidence items_" in report.to_markdown()


def test_report_verdict_icon_confirmed():
    item = EvidenceItem(check="symbol_exists", verdict="CONFIRMED", summary="exists")
    report = Report(claim_type="symbols", evidence=[item], sandboxed=True)
    md = report.to_markdown()
    assert "✓" in md
    assert "CONFIRMED" in md
    assert "Isolation: **strong** (Docker)" in md


def test_report_sandbox_lines():
    item = EvidenceItem(check="x", verdict="WARNING", summary="s")
    assert "Isolation: **weak** (restricted subprocess)" in Report(
        "symbols", [item], sandboxed=False
    ).to_markdown()
    assert "Isolation: **unknown**" in Report("symbols", [item], sandboxed=None).to_markdown()


def test_report_details_rendered_when_present():
    item = EvidenceItem(
        check="reproduction", verdict="REFUTED", summary="no repro", details="traceback..."
    )
    md = Report(claim_type="reproduction", evidence=[item], sandboxed=False).to_markdown()
    assert "<details>" in md
    assert "traceback..." in md
    assert "</details>" in md


def test_report_no_details_placeholder():
    item = EvidenceItem(check="reproduction", verdict="REFUTED", summary="no repro")
    md = Report(claim_type="reproduction", evidence=[item], sandboxed=False).to_markdown()
    assert "_no additional details_" in md


def test_report_unknown_verdict_falls_back_to_q():
    item = EvidenceItem(check="mystery", verdict="WEIRD", summary="s")
    md = Report(claim_type="pr_coverage", evidence=[item], sandboxed=False).to_markdown()
    assert "?" in md


# ---------------------------------------------------------------------------
# from_checks factory — one branch per claim type
# ---------------------------------------------------------------------------
def _evidence_dict(**overrides) -> dict:
    base = {
        "check": "pr_coverage",
        "verdict": "WARNING",
        "summary": "! No test covers the change",
        "details": "calc.py:3",
        "isolation": "weak",
    }
    base.update(overrides)
    return base


def test_from_checks_symbols():
    symbols = [_evidence_dict(check="symbol_exists", verdict="REFUTED")]
    report = Report.from_checks(
        "symbols", symbols_evidence=symbols, sandboxed=False
    )
    assert len(report.evidence) == 1
    assert report.evidence[0].check == "symbol_exists"
    assert report.evidence[0].verdict == "REFUTED"


def test_from_checks_reproduction():
    report = Report.from_checks(
        "reproduction",
        repro_evidence=[_evidence_dict(check="reproduction", verdict="CONFIRMED")],
        sandboxed=True,
    )
    assert report.evidence[0].verdict == "CONFIRMED"
    assert report.sandboxed is True


def test_from_checks_pr_coverage():
    report = Report.from_checks(
        "pr_coverage", pr_cov_evidence=[_evidence_dict()], sandboxed=False
    )
    assert report.evidence[0].check == "pr_coverage"
    assert report.evidence[0].details == "calc.py:3"


def test_from_checks_defaults_missing_keys():
    report = Report.from_checks("symbols", symbols_evidence=[{}])
    assert report.evidence[0].check == "unknown"
    assert report.evidence[0].verdict == "INCONCLUSIVE"


def test_from_checks_wrong_type_falls_back_to_inconclusive():
    # pass symbols evidence for a "pr_coverage" claim type -> the branch
    # does not match, so the fallback placeholder item is emitted
    report = Report.from_checks(
        "pr_coverage", symbols_evidence=[_evidence_dict(check="symbol_exists")]
    )
    assert report.evidence[0].check == "unknown"
    assert report.evidence[0].summary == "no check results available"


def test_from_checks_ignores_other_type_evidence():
    report = Report.from_checks(
        "symbols",
        symbols_evidence=[_evidence_dict(check="symbol_exists", verdict="CONFIRMED")],
        repro_evidence=[_evidence_dict(check="reproduction")],
        pr_cov_evidence=[_evidence_dict(check="pr_coverage")],
    )
    assert len(report.evidence) == 1  # only the matching list is used
    assert report.evidence[0].check == "symbol_exists"


# ---------------------------------------------------------------------------
# run_report convenience wrapper
# ---------------------------------------------------------------------------
def test_run_report_returns_markdown():
    md = run_report(
        "pr_coverage",
        pr_cov_evidence=[_evidence_dict()],
        sandboxed=False,
    )
    assert isinstance(md, str)
    assert "pr_coverage" in md
    assert "No test covers the change" in md

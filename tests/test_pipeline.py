"""Pipeline tests: run_triage end-to-end (no Docker needed for symbol/version checks)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claimcheck import pipeline
from claimcheck.models import Evidence, ReportType, Verdict
from claimcheck.report import render_markdown, to_json_dict

# --- triage ------------------------------------------------------------------


def test_overall_refuted_wins():
    evidence = [
        Evidence(check="a", verdict=Verdict.CONFIRMED, summary="ok"),
        Evidence(check="b", verdict=Verdict.REFUTED, summary="fail"),
    ]
    assert pipeline.overall(evidence) == Verdict.REFUTED


def test_overall_warning_beats_confirmed():
    evidence = [
        Evidence(check="reproduction", verdict=Verdict.CONFIRMED, summary="ok"),
        Evidence(check="b", verdict=Verdict.WARNING, summary="hmm"),
    ]
    assert pipeline.overall(evidence) == Verdict.WARNING


def test_overall_confirmed_needs_confirming_check():
    evidence = [Evidence(check="symbol_exists", verdict=Verdict.CONFIRMED, summary="ok")]
    assert pipeline.overall(evidence) == Verdict.INCONCLUSIVE

    evidence2 = [Evidence(check="reproduction", verdict=Verdict.CONFIRMED, summary="ok")]
    assert pipeline.overall(evidence2) == Verdict.CONFIRMED


def test_overall_empty_is_inconclusive():
    assert pipeline.overall([]) == Verdict.INCONCLUSIVE


def test_run_triage_symbol_not_found(sample_project):
    rep = pipeline.run_triage("parse_url_v99() is broken", sample_project)
    assert rep.overall in (Verdict.REFUTED, Verdict.INCONCLUSIVE)
    assert rep.claim.type == ReportType.BUG


def test_run_triage_with_snippet(sample_project):
    rep = pipeline.run_triage(
        "Bug: crash\n```python\nraise ValueError('boom')\n```",
        sample_project,
    )
    # Reproduction should run; verdict depends on sandbox availability
    assert rep.overall in (Verdict.CONFIRMED, Verdict.INCONCLUSIVE)


def test_run_triage_json_shape(sample_project):
    rep = pipeline.run_triage("symbol_check_test: import calc", sample_project)
    data = json.loads(json.dumps(to_json_dict(rep), default=str))
    assert "verdict" in data
    assert "claim" in data
    assert "evidence" in data


def test_run_triage_no_llm(sample_project):
    """Runs fine with use_llm=False (the default)."""
    rep = pipeline.run_triage("something is broken", sample_project, use_llm=False)
    assert rep.claim.type in ReportType


def test_markdown_report_contains_verdict(sample_project):
    rep = pipeline.run_triage("import calc", sample_project)
    md = render_markdown(rep)
    assert "Verdict" in md


# A realistic end-to-end test that actually attempts the sandbox
@pytest.mark.docker
def test_end_to_end_real_sandbox_crash_is_confirmed(sample_project):
    """Works with Docker (strong) or without (weak); only the verdict is asserted."""
    rep = pipeline.run_triage("Crash\n```python\nraise ValueError('boom')\n```", sample_project)
    assert rep.overall == Verdict.CONFIRMED


# --- pull requests: run_pr, git helpers --------------------------------------


def _fake_pr_checker(items):
    calls = []

    def fake(repo, diff_text, *, claim=None, timeout=60.0):
        calls.append({"repo": repo, "claim": claim, "diff": diff_text})
        return items

    fake.calls = calls
    return fake


def _pr_item(verdict, check="pr_coverage", isolation="strong"):
    return {
        "check": check,
        "verdict": verdict,
        "summary": f"{verdict} item",
        "details": "tail",
        "isolation": isolation,
    }


def test_run_pr_confirmed_when_added_lines_are_covered(monkeypatch, tmp_path):
    fake = _fake_pr_checker([_pr_item("CONFIRMED")])
    monkeypatch.setattr(pipeline, "check_pr_coverage", fake)
    rep = pipeline.run_pr("diff text", tmp_path)
    assert rep.overall == Verdict.CONFIRMED
    assert rep.evidence[0].verdict == Verdict.CONFIRMED
    assert rep.evidence[0].sandboxed is True
    assert "Isolation: **strong**" in render_markdown(rep)


def test_run_pr_warning_and_refuted_map_through(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "check_pr_coverage", _fake_pr_checker([_pr_item("WARNING")]))
    assert pipeline.run_pr("d", tmp_path).overall == Verdict.WARNING
    monkeypatch.setattr(
        pipeline,
        "check_pr_coverage",
        _fake_pr_checker([_pr_item("CONFIRMED"), _pr_item("REFUTED")]),
    )
    assert pipeline.run_pr("d", tmp_path).overall == Verdict.REFUTED


def test_run_pr_passes_the_claim_so_adds_tests_is_checked(monkeypatch, tmp_path):
    fake = _fake_pr_checker([_pr_item("CONFIRMED")])
    monkeypatch.setattr(pipeline, "check_pr_coverage", fake)
    rep = pipeline.run_pr("d", tmp_path, description="Fixes #12, adds tests")
    assert rep.claim.type == ReportType.PULL_REQUEST
    assert fake.calls[0]["claim"].claims_tests is True


def test_adds_tests_warning_beats_a_covered_pr(monkeypatch, tmp_path):
    items = [_pr_item("CONFIRMED"), _pr_item("WARNING", check="claims_tests", isolation="n/a")]
    monkeypatch.setattr(pipeline, "check_pr_coverage", _fake_pr_checker(items))
    assert pipeline.run_pr("d", tmp_path, description="adds tests").overall == Verdict.WARNING


def test_inconclusive_pr_has_no_isolation_claim(monkeypatch, tmp_path):
    item = _pr_item("INCONCLUSIVE", isolation="n/a")
    monkeypatch.setattr(pipeline, "check_pr_coverage", _fake_pr_checker([item]))
    rep = pipeline.run_pr("d", tmp_path)
    assert rep.overall == Verdict.INCONCLUSIVE
    assert "no code was executed" in render_markdown(rep)


def test_pr_json_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "check_pr_coverage", _fake_pr_checker([_pr_item("WARNING")]))
    data = json.loads(json.dumps(to_json_dict(pipeline.run_pr("d", tmp_path)), default=str))
    assert data["verdict"] == "warning"
    assert data["claim"]["type"] == "pr"
    assert data["evidence"][0]["check"] == "pr_coverage"


def test_git_diff_between_refs(pr_repo):
    diff = pipeline.git_diff(pr_repo, "main", "feature")
    assert "+++ b/calc.py" in diff
    assert "+def sub(a, b):" in diff


@pytest.mark.parametrize("base,head", [("-x", "main"), ("main", "--output=/tmp/x"), ("", "main")])
def test_git_diff_rejects_option_like_refs(pr_repo, base, head):
    with pytest.raises(ValueError):
        pipeline.git_diff(pr_repo, base, head)


def test_git_diff_unknown_ref_is_value_error(pr_repo):
    with pytest.raises(ValueError):
        pipeline.git_diff(pr_repo, "main", "no-such-branch")


def test_checked_out_tests_the_head_commit_and_cleans_up(pr_repo):
    with pipeline.checked_out(pr_repo, "feature") as work:
        assert "def sub" in (work / "calc.py").read_text()
        kept = work
    assert not kept.exists()  # temp copy removed
    assert "def sub" not in (pr_repo / "calc.py").read_text()  # original untouched


def test_checked_out_bad_ref(pr_repo):
    with pytest.raises(ValueError), pipeline.checked_out(pr_repo, "no-such-branch"):
        pass
    with pytest.raises(ValueError), pipeline.checked_out(pr_repo, "-f"):
        pass


def test_checked_out_ignores_repo_hooks(pr_repo):
    hook = pr_repo / ".git" / "hooks" / "post-checkout"
    marker = Path(str(pr_repo) + ".hook-ran")
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    with pipeline.checked_out(pr_repo, "feature"):
        pass
    assert not marker.exists()


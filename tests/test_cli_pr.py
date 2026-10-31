"""CLI tests for ``claimcheck pr`` (the coverage check is faked: no Docker, no Ollama)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claimcheck import pipeline
from claimcheck.cli import app

runner = CliRunner()

_DIFF = "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1 +1,2 @@\n a\n+b\n"


def _item(verdict, check="pr_coverage", isolation="strong"):
    return {
        "check": check,
        "verdict": verdict,
        "summary": f"{verdict} item",
        "details": "",
        "isolation": isolation,
    }


def _fake(monkeypatch, *items):
    calls = []

    def fake(repo, diff_text, *, claim=None, timeout=60.0):
        calls.append({"repo": str(repo), "diff": diff_text, "claim": claim})
        return list(items)

    monkeypatch.setattr(pipeline, "check_pr_coverage", fake)
    return calls


def _diff_file(tmp_path, text=_DIFF):
    path = tmp_path / "change.patch"
    path.write_text(text, encoding="utf-8")
    return path


def _run(sample_project, *args):
    return runner.invoke(app, ["pr", "--repo", str(sample_project), "--no-llm", *args])


@pytest.mark.parametrize(
    "verdict,code",
    [("CONFIRMED", 0), ("REFUTED", 1), ("WARNING", 2), ("INCONCLUSIVE", 2)],
)
def test_exit_codes_follow_the_verdict(monkeypatch, tmp_path, sample_project, verdict, code):
    _fake(monkeypatch, _item(verdict))
    result = _run(sample_project, "--diff-file", str(_diff_file(tmp_path)))
    assert result.exit_code == code
    assert verdict in result.output


def test_json_output(monkeypatch, tmp_path, sample_project):
    _fake(monkeypatch, _item("WARNING"))
    result = _run(sample_project, "--diff-file", str(_diff_file(tmp_path)), "--json")
    assert result.exit_code == 2
    assert json.loads(result.output)["verdict"] == "warning"


def test_reads_diff_from_stdin(monkeypatch, sample_project):
    calls = _fake(monkeypatch, _item("CONFIRMED"))
    result = runner.invoke(
        app, ["pr", "--repo", str(sample_project), "--diff-file", "-", "--no-llm"], input=_DIFF
    )
    assert result.exit_code == 0
    assert calls[0]["diff"] == _DIFF


def test_description_feeds_the_adds_tests_claim(monkeypatch, tmp_path, sample_project):
    calls = _fake(monkeypatch, _item("CONFIRMED"))
    desc = tmp_path / "pr.md"
    desc.write_text("Fixes #3, adds tests", encoding="utf-8")
    _run(sample_project, "--diff-file", str(_diff_file(tmp_path)), "--report", str(desc))
    assert calls[0]["claim"].claims_tests is True


def test_base_head_tests_the_head_commit_not_the_working_tree(monkeypatch, pr_repo):
    seen = {}

    def fake(repo, diff_text, *, claim=None, timeout=60.0):
        seen["calc"] = (Path(repo) / "calc.py").read_text()
        seen["diff"] = diff_text
        return [_item("CONFIRMED")]

    monkeypatch.setattr(pipeline, "check_pr_coverage", fake)
    result = runner.invoke(
        app, ["pr", "--repo", str(pr_repo), "--base", "main", "--head", "feature", "--no-llm"]
    )
    assert result.exit_code == 0
    assert "def sub" in seen["calc"]  # head checkout, though the repo sits on main
    assert "+def sub(a, b):" in seen["diff"]


@pytest.mark.parametrize(
    "args",
    [
        [],  # no diff source
        ["--base", "main"],  # --head missing
        ["--head", "feature"],  # --base missing
        ["--diff-file", "x.patch", "--base", "main", "--head", "feature"],  # both
    ],
)
def test_bad_source_combinations_are_usage_errors(monkeypatch, sample_project, args):
    _fake(monkeypatch, _item("CONFIRMED"))
    assert _run(sample_project, *args).exit_code == 3


def test_missing_diff_file(monkeypatch, tmp_path, sample_project):
    _fake(monkeypatch, _item("CONFIRMED"))
    assert _run(sample_project, "--diff-file", str(tmp_path / "nope.patch")).exit_code == 3


def test_repo_must_be_directory(monkeypatch, tmp_path):
    _fake(monkeypatch, _item("CONFIRMED"))
    result = runner.invoke(
        app, ["pr", "--repo", str(tmp_path / "missing"), "--diff-file", str(_diff_file(tmp_path))]
    )
    assert result.exit_code == 3


def test_option_like_ref_is_rejected(monkeypatch, sample_project):
    _fake(monkeypatch, _item("CONFIRMED"))
    assert _run(sample_project, "--base=-x", "--head=main").exit_code == 3


def test_pr_help_lists_options():
    result = runner.invoke(app, ["pr", "--help"])
    assert result.exit_code == 0
    for opt in ("--repo", "--diff-file", "--base", "--head", "--report", "--no-llm", "--json"):
        assert opt in result.output


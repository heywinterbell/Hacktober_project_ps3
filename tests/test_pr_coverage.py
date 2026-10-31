"""Tests for ``src/claimcheck/checks/pr_coverage.py``.

CI-safe: the sandbox is faked with canned pytest output and canned coverage
JSON, so no Docker, no pytest-in-pytest. One ``docker``-marked test runs the
real thing and is skipped when Docker or the image is missing.
"""

from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace

import pytest

from claimcheck.checks import pr_coverage
from claimcheck.checks.pr_coverage import (
    _is_test_path,
    _production_added_lines,
    _split_output,
    build_coverage_command,
    check_pr_coverage,
    intersect_uncovered,
)
from claimcheck.sandbox import STRONG, WEAK, SandboxResult, docker_available

_ADD_SUB_DIFF = "\n".join(
    [
        "diff --git a/calc.py b/calc.py",
        "--- a/calc.py",
        "+++ b/calc.py",
        "@@ -1,2 +1,4 @@",
        " def add(a, b):",
        "     return a + b",
        "+def sub(a, b):",
        "+    return a - b",
    ]
)

_TEST_ONLY_DIFF = "\n".join(
    [
        "diff --git a/tests/test_calc.py b/tests/test_calc.py",
        "--- a/tests/test_calc.py",
        "+++ b/tests/test_calc.py",
        "@@ -1,1 +1,2 @@",
        " import calc",
        "+def test_new(): pass",
    ]
)


def _cov(executed, missing, path="calc.py"):
    return {"files": {path: {"executed_lines": executed, "missing_lines": missing}}}


def _fake_sandbox(monkeypatch, *, coverage=None, exit_code=0, isolation=STRONG,
                  timed_out=False, pytest_text="1 passed"):
    """Replace ``run_in_sandbox`` in pr_coverage; return the recorded calls."""
    calls: list[dict] = []

    def fake(repo, argv, **kwargs):
        calls.append({"repo": repo, "argv": argv, **kwargs})
        marker = re.search(r"@@CLAIMCHECK-COVERAGE-\w+@@", argv[2]).group(0)
        blob = json.dumps(coverage) if coverage is not None else ""
        return SandboxResult(
            stdout=f"{pytest_text}\n{marker}\n{blob}",
            stderr="",
            exit_code=exit_code,
            timed_out=timed_out,
            duration=0.1,
            isolation=isolation,
            command=argv,
        )

    monkeypatch.setattr(pr_coverage, "run_in_sandbox", fake)
    return calls


def _no_sandbox(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("sandbox must not run")

    monkeypatch.setattr(pr_coverage, "run_in_sandbox", boom)


# --- intersect_uncovered ------------------------------------------------------


def test_intersect_uncovered_no_uncovered():
    cov = {"files": {"calc.py": {"executed_lines": [1, 2]}}}
    assert intersect_uncovered({"calc.py": {1, 2}}, cov) == {}


def test_intersect_uncovered_with_uncovered():
    cov = {"files": {"calc.py": {"executed_lines": [1, 2]}}}
    assert intersect_uncovered({"calc.py": {1, 2, 3}}, cov) == {"calc.py": {3}}


def test_intersect_uncovered_multiple_files():
    cov = {"files": {"calc.py": {"executed_lines": [1]}, "utils.py": {"executed_lines": []}}}
    assert intersect_uncovered({"calc.py": {1}, "utils.py": {5}}, cov) == {"utils.py": {5}}


def test_intersect_ignores_non_executable_added_lines():
    # line 3 is a comment/docstring: neither executed nor missing
    cov = _cov(executed=[1, 2], missing=[4])
    assert intersect_uncovered({"calc.py": {3, 4}}, cov) == {"calc.py": {4}}


def test_intersect_matches_workspace_and_dot_prefixes():
    cov = _cov(executed=[], missing=[2], path="/workspace/calc.py")
    assert intersect_uncovered({"./calc.py": {2}}, cov) == {"./calc.py": {2}}
    assert intersect_uncovered({"calc.py": {2}}, _cov([2], [], "./calc.py")) == {}


def test_file_absent_from_coverage_is_fully_uncovered():
    assert intersect_uncovered({"new.py": {1, 2}}, {"files": {}}) == {"new.py": {1, 2}}


# --- path filters -------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["tests/test_calc.py", "pkg/test/x.py", "test_calc.py", "calc_test.py", "conftest.py"]
)
def test_is_test_path_true(path):
    assert _is_test_path(path)


@pytest.mark.parametrize("path", ["calc.py", "latest.py", "contest.py", "src/pkg/utils.py"])
def test_is_test_path_false(path):
    assert not _is_test_path(path)


def test_production_lines_skip_tests_and_non_python():
    diff = {"calc.py": {1}, "README.md": {1}, "tests/test_calc.py": {1}, "gone.py": set()}
    assert _production_added_lines(diff) == [("calc.py", {1})]


# --- the suite runs through the sandbox, never on the host --------------------


def test_module_does_not_use_subprocess_directly():
    assert not hasattr(pr_coverage, "subprocess")


def test_runs_through_sandbox_with_tmp_paths_only(monkeypatch, tmp_path):
    calls = _fake_sandbox(monkeypatch, coverage=_cov([1, 2, 3, 4], []))
    check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert len(calls) == 1
    call = calls[0]
    script = call["argv"][2]
    assert call["argv"][:2] == ["sh", "-c"]
    for needle in (
        "COVERAGE_FILE=/tmp/",
        "python -B -m pytest",
        "-p no:cacheprovider",
        "--cov-report=json:/tmp/",
    ):
        assert needle in script
    assert call["max_output_bytes"] >= 1024 * 1024  # coverage JSON must not be cut
    assert str(call["repo"]) == str(tmp_path)


def test_command_uses_unique_token_and_forwards_no_env():
    argv_a, marker_a = build_coverage_command("aaa")
    argv_b, marker_b = build_coverage_command("bbb")
    assert marker_a != marker_b
    assert "/tmp/cc-aaa.json" in argv_a[2] and "/tmp/cc-aaa.json" not in argv_b[2]


# --- verdicts -----------------------------------------------------------------


def test_all_added_lines_covered_is_confirmed(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, coverage=_cov([1, 2, 3, 4], []))
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert [e["verdict"] for e in ev] == ["CONFIRMED"]
    assert "All 2 added production lines are covered" in ev[0]["summary"]
    assert ev[0]["isolation"] == STRONG


def test_uncovered_lines_warn_and_name_them(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, coverage=_cov([1, 2], [3, 4]))
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert ev[0]["verdict"] == "WARNING"
    assert "No test covers the change" in ev[0]["summary"]
    assert "calc.py:3, 4" in ev[0]["details"]


def test_weak_isolation_is_labelled(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, coverage=_cov([1, 2, 3, 4], []), isolation=WEAK)
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert "[weak isolation]" in ev[0]["summary"]
    assert ev[0]["isolation"] == WEAK


def test_failing_suite_is_refuted(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, exit_code=1, pytest_text="1 failed")
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert ev[0]["verdict"] == "REFUTED"
    assert "test suite fails" in ev[0]["summary"]
    assert "1 failed" in ev[0]["details"]


@pytest.mark.parametrize("code", [2, 3, 4])
def test_suite_that_cannot_run_is_inconclusive(monkeypatch, tmp_path, code):
    _fake_sandbox(monkeypatch, exit_code=code, pytest_text="ModuleNotFoundError: requests")
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert ev[0]["verdict"] == "INCONCLUSIVE"
    assert "could not run the test suite" in ev[0]["summary"]
    assert "requests" in ev[0]["details"]


def test_no_tests_collected_still_measures_coverage(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, exit_code=5, coverage=_cov([], [1, 2, 3, 4]))
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert ev[0]["verdict"] == "WARNING"


def test_timeout_is_inconclusive(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, exit_code=-9, timed_out=True)
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert ev[0]["verdict"] == "INCONCLUSIVE"
    assert "timed out" in ev[0]["summary"]


def test_missing_coverage_json_is_inconclusive(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, coverage=None)
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF)
    assert ev[0]["verdict"] == "INCONCLUSIVE"
    assert "no coverage JSON" in ev[0]["summary"]


# --- nothing to measure: the suite is not run ---------------------------------


def test_empty_diff_is_inconclusive_without_running(monkeypatch, tmp_path):
    _no_sandbox(monkeypatch)
    ev = check_pr_coverage(str(tmp_path), "")
    assert ev[0]["verdict"] == "INCONCLUSIVE"
    assert "no production code lines added" in ev[0]["summary"]


def test_test_only_diff_is_inconclusive_without_running(monkeypatch, tmp_path):
    _no_sandbox(monkeypatch)
    ev = check_pr_coverage(str(tmp_path), _TEST_ONLY_DIFF)
    assert ev[0]["verdict"] == "INCONCLUSIVE"


# --- claims_tests -------------------------------------------------------------


def test_claims_tests_but_no_test_files_warns(monkeypatch, tmp_path):
    _fake_sandbox(monkeypatch, coverage=_cov([1, 2, 3, 4], []))
    claim = SimpleNamespace(claims_tests=True)
    ev = check_pr_coverage(str(tmp_path), _ADD_SUB_DIFF, claim=claim)
    items = [e for e in ev if e["check"] == "claims_tests"]
    assert items and items[0]["verdict"] == "WARNING"
    assert "diff touches no test files" in items[0]["summary"]


def test_claims_tests_with_test_files_adds_nothing(monkeypatch, tmp_path):
    _no_sandbox(monkeypatch)
    claim = SimpleNamespace(claims_tests=True)
    ev = check_pr_coverage(str(tmp_path), _TEST_ONLY_DIFF, claim=claim)
    assert not [e for e in ev if e["check"] == "claims_tests"]


def test_claims_tests_flagged_even_when_nothing_to_measure(monkeypatch, tmp_path):
    _no_sandbox(monkeypatch)
    readme = "\n".join(
        [
            "diff --git a/README.md b/README.md",
            "--- a/README.md",
            "+++ b/README.md",
            "@@ -1 +1,2 @@",
            " a",
            "+b",
        ]
    )
    ev = check_pr_coverage(str(tmp_path), readme, claim=SimpleNamespace(claims_tests=True))
    assert {e["check"] for e in ev} == {"pr_coverage", "claims_tests"}


# --- output parsing: untrusted test output must not forge coverage ------------


def test_split_output_uses_the_real_marker_only():
    real = "@@CLAIMCHECK-COVERAGE-real@@"
    forged = "@@CLAIMCHECK-COVERAGE-evil@@"
    out = f"1 passed\n{forged}\n{{\"files\": {{}}}}\n{real}\n{{\"files\": {{\"a.py\": {{}}}}}}"
    text, data = _split_output(out, real)
    assert data == {"files": {"a.py": {}}}
    assert "1 passed" in text


def test_split_output_without_marker_or_bad_json():
    assert _split_output("1 passed", "@@M@@") == ("1 passed", None)
    assert _split_output("x\n@@M@@\nnot json", "@@M@@")[1] is None
    assert _split_output("x\n@@M@@\n[1, 2]", "@@M@@")[1] is None


# --- real sandbox (skipped without Docker or the rebuilt image) ---------------


def _image_has_pytest_cov() -> bool:
    if not docker_available():
        return False
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "claimcheck-sandbox:latest",
         "python", "-c", "import pytest_cov"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    return proc.returncode == 0


@pytest.mark.docker
@pytest.mark.skipif(not _image_has_pytest_cov(), reason="needs Docker and a rebuilt sandbox image")
def test_real_docker_run_reports_strong_isolation(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n"
    )
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    diff = "\n".join(
        [
            "diff --git a/calc.py b/calc.py",
            "--- a/calc.py",
            "+++ b/calc.py",
            "@@ -1,3 +1,5 @@",
            " def add(a, b):",
            "     return a + b",
            " ",
            "+def sub(a, b):",
            "+    return a - b",
        ]
    )
    ev = check_pr_coverage(str(tmp_path), diff, timeout=120)
    assert ev[0]["isolation"] == STRONG
    assert ev[0]["verdict"] == "WARNING"  # sub() is never called by the suite

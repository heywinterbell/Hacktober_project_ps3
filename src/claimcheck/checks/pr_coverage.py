"""PR coverage check: intersect unified-diff changed lines with pytest coverage.

Responsible for the ``! No test covers the change`` case (PR case).

The target repo's test suite is untrusted code, so it only ever runs through
:func:`claimcheck.sandbox.run_in_sandbox` (Docker when available).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claimcheck.diffparse import parse_unified_diff
from claimcheck.models import Claim as ClaimModel
from claimcheck.sandbox import STRONG, WEAK, run_in_sandbox

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_COVERAGE_BYTES = 2 * 1024 * 1024  # coverage JSON must not be truncated
_TAIL_CHARS = 800


def _is_test_path(path: str) -> bool:
    """Return True if *path* is a test file (test dir, ``test_*.py``, ``*_test.py``)."""
    norm = os.path.normpath(path).replace("\\", "/")
    parts = norm.split("/")
    base = parts[-1]
    in_test_dir = any(p in ("tests", "test") for p in parts[:-1])
    test_name = base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"
    return in_test_dir or test_name


def _production_added_lines(diff: dict[str, set[int]]) -> list[tuple[str, set[int]]]:
    """Return ``(filepath, added_line_numbers)`` for *production* files only.

    Excludes test files, non-Python files (docs, configs: coverage cannot measure
    them), binary files, and deleted files.
    """
    result: list[tuple[str, set[int]]] = []
    for filepath, added in diff.items():
        if not filepath or not filepath.endswith(".py"):
            continue
        if _is_test_path(filepath):
            continue
        if not added:
            continue
        result.append((filepath, added))
    return result


def intersect_uncovered(diff: dict[str, set[int]], coverage: dict[str, Any]) -> dict[str, set[int]]:
    """Return a dict mapping *filepath* → set of added line numbers **not** covered.

    Coverage JSON is expected in the standard ``coverage`` format::

        {
            "files": {
                "path/to/file.py": {
                    "executed_lines": [1, 2, 3, ...],
                    ...
                },
                ...
            },
            "totals": {...}
        }

    Lines are 1‑indexed.
    """
    uncovered: dict[str, set[int]] = {}
    files_in_coverage = {
        _norm_path(path): data for path, data in coverage.get("files", {}).items()
    }
    for filepath, added_lines in diff.items():
        if not added_lines:
            continue
        file_data = files_in_coverage.get(_norm_path(filepath))
        if file_data is not None and "missing_lines" in file_data:
            # Only executable lines count: comments, blanks and docstrings that
            # a PR adds are neither executed nor missing, so they are ignored.
            uncovered_lines = added_lines & set(file_data["missing_lines"])
        else:
            executed_set = set(file_data.get("executed_lines", [])) if file_data else set()
            uncovered_lines = added_lines - executed_set
        if uncovered_lines:
            uncovered[filepath] = uncovered_lines
    return uncovered


def _norm_path(path: str) -> str:
    """Make coverage and diff paths comparable (``./x``, ``/workspace/x`` → ``x``)."""
    norm = path.replace("\\", "/")
    for prefix in ("/workspace/", "./"):
        if norm.startswith(prefix):
            norm = norm[len(prefix):]
    return norm


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

@dataclass
class CoverageRun:
    """Outcome of running the suite with coverage inside the sandbox."""

    coverage: dict[str, Any] | None
    reason: str  # "ok" | "suite_failed" | "not_runnable" | "timeout" | "no_coverage"
    isolation: str  # STRONG | WEAK
    exit_code: int | None
    output: str  # tail of pytest output, for the evidence details


def build_coverage_command(token: str) -> tuple[list[str], str]:
    """Return ``(argv, marker)`` for the sandboxed pytest-with-coverage run.

    The repo mount is read-only, so the coverage data file, the JSON report and
    bytecode all go to ``/tmp``. No environment is forwarded: the variables are
    set in the shell line itself. ``marker`` separates pytest's own output from
    the JSON; it carries a random token so test output cannot forge it.
    """
    cov_json = f"/tmp/cc-{token}.json"
    cov_data = f"/tmp/.cc-cov-{token}"
    marker = f"@@CLAIMCHECK-COVERAGE-{token}@@"
    script = (
        f"COVERAGE_FILE={cov_data} python -B -m pytest -q -p no:cacheprovider "
        f"--cov=. --cov-report=json:{cov_json}; rc=$?; "
        f"printf '\\n%s\\n' {marker}; cat {cov_json} 2>/dev/null; "
        f"rm -f {cov_json} {cov_data}; exit $rc"
    )
    return ["sh", "-c", script], marker


def _split_output(stdout: str, marker: str) -> tuple[str, dict[str, Any] | None]:
    """Split sandbox stdout into pytest text and the parsed coverage JSON."""
    text, sep, blob = stdout.rpartition(marker)
    if not sep:
        return stdout, None
    try:
        data = json.loads(blob.strip())
    except ValueError:
        return text, None
    return text, data if isinstance(data, dict) else None


def _run_pytest_with_coverage(repo_path: str, *, timeout: float = 60.0) -> CoverageRun:
    """Run the repo's suite with ``pytest-cov`` through ``run_in_sandbox``.

    Never runs on the host directly. pytest exit codes: 0 pass, 1 tests failed,
    5 no tests collected (coverage still usable); 2-4 mean the suite could not
    run here (for example the sandbox image lacks the repo's dependencies).
    """
    argv, marker = build_coverage_command(uuid.uuid4().hex[:12])
    result = run_in_sandbox(
        Path(repo_path), argv, timeout=timeout, max_output_bytes=_MAX_COVERAGE_BYTES
    )
    isolation = result.isolation if result.isolation in (STRONG, WEAK) else WEAK
    text, coverage = _split_output(result.stdout, marker)
    tail = (text.strip() or result.stderr.strip())[-_TAIL_CHARS:]

    def run(reason: str, cov: dict[str, Any] | None = None) -> CoverageRun:
        return CoverageRun(cov, reason, isolation, result.exit_code, tail)

    if result.timed_out:
        return run("timeout")
    if result.exit_code is None:
        return run("not_runnable")
    if result.exit_code == 1:
        return run("suite_failed")
    if result.exit_code not in (0, 5):
        return run("not_runnable")
    if coverage is None:
        return run("no_coverage")
    return run("ok", coverage)


_REASON_TEXT = {
    "timeout": "test run timed out in the sandbox",
    "not_runnable": (
        "could not run the test suite in the sandbox "
        "(the image only has pytest and pytest-cov, not the repo's own dependencies)"
    ),
    "no_coverage": "tests ran but no coverage JSON was produced",
}


def _item(
    verdict: str,
    summary: str,
    details: str = "",
    isolation: str = "n/a",
    check: str = "pr_coverage",
) -> dict[str, Any]:
    return {
        "check": check,
        "verdict": verdict,
        "summary": summary,
        "details": details,
        "isolation": isolation,
    }


def _claims_tests_items(diff: dict[str, set[int]], claim: ClaimModel | None) -> list[dict]:
    """The claim says "adds tests": flag it when the diff touches no test files.

    Must look at the full diff, not the production lines (those exclude tests).
    """
    if claim is None or not claim.claims_tests:
        return []
    if any(_is_test_path(fp) for fp in diff):
        return []
    return [
        _item(
            "WARNING",
            '✗ claim says "adds tests" but diff touches no test files',
            check="claims_tests",
        )
    ]


def check_pr_coverage(
    repo_path: str,
    diff_text: str,
    *,
    claim: ClaimModel | None = None,
    timeout: float = 60.0,
) -> list[Any]:
    """Analyse a PR diff against a sandboxed test run with coverage.

    Returns evidence dicts that combine into a final verdict:

    * suite fails -> REFUTED
    * added production lines not executed by any test -> WARNING
    * all added production lines executed -> CONFIRMED
    * suite cannot run / no production code / no coverage -> INCONCLUSIVE (with why)

    *claim* may be ``None``; its ``claims_tests`` flag adds a WARNING when the
    diff touches no test files.
    """
    diff = parse_unified_diff(diff_text)
    prod = _production_added_lines(diff)
    extra = _claims_tests_items(diff, claim)

    # Nothing to measure: do not run the suite at all.
    if not prod:
        return [_item("INCONCLUSIVE", "✗ no production code lines added in this PR"), *extra]

    run = _run_pytest_with_coverage(repo_path, timeout=timeout)
    iso = run.isolation
    marker = "" if iso == STRONG else " [weak isolation]"

    if run.reason == "suite_failed":
        return [_item("REFUTED", f"✗ test suite fails{marker}", run.output, iso), *extra]
    if run.coverage is None:
        why = _REASON_TEXT.get(run.reason, run.reason)
        return [_item("INCONCLUSIVE", f"? {why}{marker}", run.output, iso), *extra]

    uncovered = intersect_uncovered(dict(prod), run.coverage)
    if uncovered:
        parts = [
            f"{fp}:{', '.join(str(i) for i in sorted(lines))}"
            for fp, lines in sorted(uncovered.items())
        ]
        evidence = [
            _item(
                "WARNING",
                f"! No test covers the change{marker}",
                "Uncovered production lines: " + "; ".join(parts),
                iso,
            )
        ]
    else:
        total = sum(len(lines) for _, lines in prod)
        evidence = [
            _item(
                "CONFIRMED",
                f"✓ All {total} added production lines are covered by tests{marker}",
                "",
                iso,
            )
        ]
    return evidence + extra

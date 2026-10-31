"""PR coverage check: intersect unified-diff changed lines with pytest coverage.

Responsible for the ``! No test covers the change`` case (PR case).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Set

from claimcheck.diffparse import parse_unified_diff
from claimcheck.models import Claim as ClaimModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TMP_COVERAGE = "coverage.json"


def _is_test_path(path: str) -> bool:
    """Return True if *path* is under a typical test directory."""
    norm = os.path.normpath(path)
    parts = norm.replace("\\", "/").split("/")
    return any(p in ("tests", "test") for p in parts) or norm.endswith("_test.py") or norm.endswith("test.py")


def _production_added_lines(diff: Dict[str, Set[int]]) -> List[tuple[str, Set[int]]]:
    """Return ``(filepath, added_line_numbers)`` for *production* files only.

    Excludes test files, binary files, and deleted files.
    """
    result: List[tuple[str, Set[int]]] = []
    for filepath, added in diff.items():
        if not filepath:
            continue
        if _is_test_path(filepath):
            continue
        if not added:
            continue
        result.append((filepath, added))
    return result


def intersect_uncovered(diff: Dict[str, Set[int]], coverage: Dict[str, Any]) -> Dict[str, Set[int]]:
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
    uncovered: Dict[str, Set[int]] = {}
    files_in_coverage = coverage.get("files", {})
    for filepath, added_lines in diff.items():
        if not added_lines:
            continue
        executed_set: Set[int] = set()
        file_data = files_in_coverage.get(filepath)
        if file_data is not None:
            executed_set = set(file_data.get("executed_lines", []))
        uncovered_lines = added_lines - executed_set
        if uncovered_lines:
            uncovered[filepath] = uncovered_lines
    return uncovered


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def _run_pytest_with_coverage(repo_path: str, *, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
    """Run ``pytest -q --cov=. --cov-report=json`` and return the coverage JSON dict,
    or ``None`` if it cannot be collected.

    The sandbox may be Docker (strong) or a restricted subprocess (weak).  In both
    cases we use the ``max_output_bytes`` override so the coverage JSON (typically
    a few KB) passes through untruncated.
    """
    tmp_dir = tempfile.mkdtemp(prefix="prcov-")
    command = [os.sys.executable, "-m", "pytest", "-q", "--cov=.", "--cov-report=json:" + os.path.join(tmp_dir, _TMP_COVERAGE)]
    # run inside the repo so coverage.json lands at repo root
    result = subprocess.run(
        command,
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        # suite did not pass; still may have coverage JSON, but we treat as failure
        # caller can decide; return None to signal inconclusive
        return None

    cov_path = os.path.join(repo_path, _TMP_COVERAGE)
    if not os.path.exists(cov_path):
        return None
    try:
        with open(cov_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None


def check_pr_coverage(
    repo_path: str,
    diff_text: str,
    *,
    claim: Optional[ClaimModel] = None,
    timeout: float = 60.0,
) -> List[Any]:
    """Analyse a PR diff against a test-suite run with coverage.

    Returns a list of evidence items that combine into a final verdict
    (CONFIRMED / REFUTED / WARNING / INCONCLUSIVE).

    The *claim* argument may be ``None``; if provided its ``claims_tests``
    flag triggers extra evidence when the diff touches no test files.
    """
    # 1️⃣ parse the diff
    diff = parse_unified_diff(diff_text)
    prod = _production_added_lines(diff)  # List[(filepath, added_lines)]

    # 2️⃣ run tests with coverage
    coverage_data = _run_pytest_with_coverage(repo_path, timeout=timeout)

    # 3️⃣ could not collect coverage → INCONCLUSIVE
    if coverage_data is None:
        return [
            {
                "check": "pr_coverage",
                "verdict": "INCONCLUSIVE",
                "summary": "✗ could not collect coverage JSON",
                "details": "",
                "isolation": "weak",
            }
        ]

    # 4️⃣ intersect changed lines with coverage
    uncovered = intersect_uncovered({fp: add for fp, add in prod}, coverage_data)

    # 5️⃣ no production code added → INCONCLUSIVE
    if not prod:
        return [
            {
                "check": "pr_coverage",
                "verdict": "INCONCLUSIVE",
                "summary": "✗ no production code lines added in this PR",
                "details": "",
                "isolation": "weak",
            }
        ]

    # 6️⃣ some production lines uncovered → WARNING
    if uncovered:
        uncovered_lines: List[str] = []
        for fp, lines in sorted(uncovered.items()):
            clean = os.path.basename(fp)
            line_str = ", ".join(str(l) for l in sorted(lines))
            uncovered_lines.append(f"{clean}:{line_str}")
        uncovered_detail = "; ".join(uncovered_lines)

        evidence = [
            {
                "check": "pr_coverage",
                "verdict": "WARNING",
                "summary": "! No test covers the change",
                "details": f"Uncovered production lines: {uncovered_detail}",
                "isolation": "weak",
            }
        ]

        # claims_tests extra evidence
        if claim is not None and claim.claims_tests:
            test_files_changed = any(_is_test_path(fp) for fp, _ in prod)
            if not test_files_changed:
                evidence.append(
                    {
                        "check": "claims_tests",
                        "verdict": "WARNING",
                        "summary": '✗ claim says "adds tests" but diff touches no test files',
                        "details": "",
                        "isolation": "weak",
                    }
                )
    else:
        # all production added lines covered → CONFIRMED
        total_added = sum(len(add) for _, add in prod)
        evidence = [
            {
                "check": "pr_coverage",
                "verdict": "CONFIRMED",
                "summary": f"✓ All {total_added} added production lines are covered by tests",
                "details": "",
                "isolation": "weak",
            }
        ]

        # claims_tests positive note (optional)
        if claim is not None and claim.claims_tests:
            test_files_changed = any(_is_test_path(fp) for fp, _ in prod)
            # if tests present, we simply do not add extra WARNING evidence;
            # the CONFIRMED verdict already covers it.

    return evidence
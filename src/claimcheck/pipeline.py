"""Pipeline: end-to-end triage and PR checks.

Decision flow (see docs/ARCHITECTURE.md):

* security or bug report: extract claim → symbol check. If any symbol is
  REFUTED and **no code is executed**. Otherwise versions, then sandboxed repro.
* bug report: versions, then sandboxed repro (on the claimed version when it
  can be checked out, otherwise on the current tree).
* pull requests are analysed with :func:`run_pr` (``claimcheck pr``), not here.

The model (optional) only helps extract the claim; every verdict below comes
from AST lookups, git metadata, or a sandboxed run.
"""

from __future__ import annotations

import contextlib
import dataclasses
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from .checks.pr_coverage import check_pr_coverage
from .checks.repro import _COPY_IGNORE, reproduce
from .checks.symbols import check_symbols
from .checks.version import check_versions
from .extract import extract_from_text
from .models import Evidence, Report, Verdict

# Only a real reproduction can confirm a claim; "the name exists" or "the tag
# exists" are necessary conditions, not proof.
_CONFIRMING_CHECKS = {"reproduction", "pr_coverage"}


def overall(evidence: list[Evidence]) -> Verdict:
    """Aggregate evidence into a single verdict.

    Priority: REFUTED > WARNING > CONFIRMED > INCONCLUSIVE.
    A claim is only CONFIRMED when at least one *confirming* check
    (reproduction or pr_coverage) says so.
    """
    verdicts = {e.verdict for e in evidence}
    if Verdict.REFUTED in verdicts:
        return Verdict.REFUTED
    if Verdict.WARNING in verdicts:
        return Verdict.WARNING
    if Verdict.CONFIRMED in verdicts:
        confirming = any(
            e.verdict == Verdict.CONFIRMED and e.check in _CONFIRMING_CHECKS
            for e in evidence
        )
        return Verdict.CONFIRMED if confirming else Verdict.INCONCLUSIVE
    return Verdict.INCONCLUSIVE


def _finish(claim, evidence: list[Evidence]) -> Report:
    return Report(
        claim=claim,
        evidence=evidence,
        overall=overall(evidence),
    )


def run_triage(
    text: str,
    repo: Path | str,
    *,
    use_llm: bool = False,
) -> Report:
    """Run the full triage pipeline on *text* against *repo*.

    Returns a :class:`Report` with the aggregated verdict.
    """
    root = Path(repo)
    claim = extract_from_text(text, "bug", use_llm=use_llm)
    evidence: list[Evidence] = []

    # 1. symbol check
    evidence.extend(check_symbols(root, claim))
    if any(e.verdict == Verdict.REFUTED for e in evidence):
        return _finish(claim, evidence)

    # 2. version check
    evidence.extend(check_versions(root, claim))

    # 3. reproduction
    repro_claim = dataclasses.replace(claim, repro_snippet=claim.repro_snippet or text)
    evidence.append(reproduce(root, repro_claim))
    return _finish(claim, evidence)


def _to_evidence(item: dict) -> Evidence:
    """Convert a ``pr_coverage`` evidence dict into the shared ``Evidence`` model."""
    isolation = item.get("isolation", "n/a")
    return Evidence(
        check=item["check"],
        verdict=Verdict(str(item["verdict"]).lower()),
        summary=item["summary"],
        details={"output": item.get("details", ""), "isolation": isolation},
        sandboxed=isolation == "strong",
    )


def run_pr(
    diff_text: str,
    repo: Path | str,
    *,
    description: str = "",
    use_llm: bool = False,
    timeout: float = 60.0,
) -> Report:
    """Check a pull request: does a sandboxed test run cover the changed lines?

    ``description`` is the PR title/body; it only feeds claim extraction
    ("adds tests", ``Fixes #N``). The model never influences the verdict.
    """
    claim = extract_from_text(description or "(no description)", "pr", use_llm=use_llm)
    evidence = [_to_evidence(i) for i in check_pr_coverage(str(repo), diff_text, claim=claim)]
    return _finish(claim, evidence)


def _check_ref(ref: str) -> None:
    if not ref or ref.startswith("-"):
        raise ValueError(f"invalid git ref: {ref!r}")


def git_diff(repo: Path | str, base: str, head: str) -> str:
    """``git diff base...head`` for the PR's own changes (no external diff/textconv)."""
    _check_ref(base)
    _check_ref(head)
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv",
         f"{base}...{head}", "--"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"git diff {base}...{head} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


@contextlib.contextmanager
def checked_out(repo: Path | str, ref: str) -> Iterator[Path]:
    """Yield a temporary copy of ``repo`` checked out at ``ref`` (original untouched).

    The tests must run on the PR's head commit, not on whatever the working tree
    happens to hold. Hooks are disabled for the checkout.
    """
    _check_ref(ref)
    tmp = Path(tempfile.mkdtemp(prefix="claimcheck-pr-"))
    work = tmp / "work"
    try:
        shutil.copytree(repo, work, ignore=shutil.ignore_patterns(*_COPY_IGNORE))
        proc = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", str(work),
             "checkout", "-f", "--detach", ref],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError(f"cannot check out {ref}: {proc.stderr.strip()[:200]}")
        yield work
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


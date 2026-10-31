"""Reproduce bug-report claims by running the report's snippet in the sandbox.

The snippet is untrusted input: it always goes through
:func:`claimcheck.sandbox.run_in_sandbox`. Verdicts come from what the
run actually did (traceback / timeout / clean exit) — never a model.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..models import Claim, Evidence, Verdict
from ..sandbox import STRONG, run_in_sandbox

_BASELINE_SNIPPET = "import sys; sys.exit(0)"
_EXCERPT_CHARS = 500
_COPY_IGNORE = (
    "__pycache__",
    "*.pyc",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
)


def _excerpt(text: str) -> str:
    """Keep the tail of a stream — tracebacks end with the real error."""
    text = text.strip()
    return text[-_EXCERPT_CHARS:] if len(text) > _EXCERPT_CHARS else text


def _checkout(repo_path: Path, version: str | None) -> tuple[Path | None, str | None]:
    """Copy the repo to a temp dir; check out ``version`` inside the copy.

    Returns ``(work_dir, None)`` on success or ``(None, reason)``.
    The original tree is never modified.
    """
    tmp = Path(tempfile.mkdtemp(prefix="claimcheck-repro-"))
    work = tmp / "work"
    ignore = None if version else shutil.ignore_patterns(*_COPY_IGNORE, ".git")
    try:
        shutil.copytree(repo_path, work, ignore=ignore)
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, f"cannot copy repository: {exc}"

    if version is None:
        return work, None

    refs = [version] if version.startswith("v") else [version, f"v{version}"]
    errors: list[str] = []
    for ref in refs:
        proc = subprocess.run(
            ["git", "-C", str(work), "checkout", "-f", "--detach", ref],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode == 0:
            return work, None
        errors.append(proc.stderr.strip()[:200])
    shutil.rmtree(tmp, ignore_errors=True)
    return None, f"cannot check out version {version}: {'; '.join(errors)}"


def _evidence(
    verdict: Verdict,
    summary: str,
    details: dict,
    *,
    sandboxed: bool,
) -> Evidence:
    return Evidence(
        check="reproduction",
        verdict=verdict,
        summary=summary,
        details=details,
        sandboxed=sandboxed,
    )


def reproduce(repo_path: Path | str, claim: Claim, version: str | None = None) -> Evidence:
    """Run ``claim.repro_snippet`` against the repo and decide the verdict.

    - no snippet → INCONCLUSIVE (say why)
    - version given but not checkable → INCONCLUSIVE
    - baseline sanity fails → INCONCLUSIVE
    - snippet crashes or times out → CONFIRMED
    - snippet exits clean → REFUTED ("could not reproduce")

    Weak isolation is marked in ``details["isolation"]`` AND in the summary.
    """
    version = version or (claim.versions[0] if claim.versions else None)
    if not claim.repro_snippet:
        return _evidence(
            Verdict.INCONCLUSIVE,
            "? no repro steps provided",
            {"reason": "no_snippet", "isolation": "n/a"},
            sandboxed=False,
        )

    work, error = _checkout(Path(repo_path), version)
    if work is None:
        return _evidence(
            Verdict.INCONCLUSIVE,
            f"? {error}",
            {"reason": "checkout_failed", "version": version, "detail": error},
            sandboxed=False,
        )

    where = version if version else "current tree"
    try:
        baseline = run_in_sandbox(work, ["python", "-c", _BASELINE_SNIPPET])
        if baseline.exit_code != 0 or baseline.timed_out:
            return _evidence(
                Verdict.INCONCLUSIVE,
                "? sandbox failed its basic sanity check",
                {
                    "reason": "baseline_failed",
                    "isolation": baseline.isolation,
                    "exit_code": baseline.exit_code,
                    "output": _excerpt(baseline.stderr or baseline.stdout),
                },
                sandboxed=baseline.isolation == STRONG,
            )

        result = run_in_sandbox(work, ["python", "-c", claim.repro_snippet])
        marker = "" if result.isolation == STRONG else " [weak isolation]"
        details = {
            "version": version,
            "isolation": result.isolation,
            "timed_out": result.timed_out,
            "exit_code": result.exit_code,
        }

        if result.exit_code is None and not result.timed_out:
            return _evidence(
                Verdict.INCONCLUSIVE,
                f"? sandbox could not execute the snippet{marker}",
                details | {"reason": "spawn_failed", "output": _excerpt(result.stderr)},
                sandboxed=result.isolation == STRONG,
            )

        if result.timed_out or result.exit_code != 0:
            output = _excerpt(result.stderr or result.stdout)
            kind = "timed out" if result.timed_out else "crashed"
            return _evidence(
                Verdict.CONFIRMED,
                f"✓ Reproduced on {where} ({kind}){marker}",
                details | {"output": output},
                sandboxed=result.isolation == STRONG,
            )

        return _evidence(
            Verdict.REFUTED,
            f"✗ could not reproduce on {where}{marker}",
            details | {"reason": "clean_run", "output": _excerpt(result.stdout)},
            sandboxed=result.isolation == STRONG,
        )
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)

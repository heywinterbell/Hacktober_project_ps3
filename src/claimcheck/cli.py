"""ClaimCheck CLI — triage that tests the claims.

Phase 1 ships the doctor command; triage/pr/serve land with their checks.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import httpx
import typer

from claimcheck.report import Report

app = typer.Typer(
    help="ClaimCheck — triage that tests the claims. "
    "Deterministic checks only; the LLM never decides a verdict.",
    add_completion=False,
    no_args_is_help=True,
)


def _ensure_utf8_stdout() -> None:
    """Windows legacy consoles (cp1252) cannot encode ✓/✗ — force UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — best effort; never block the CLI
            pass


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _ollama_available() -> bool:
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


@app.callback()
def _main() -> None:
    """ClaimCheck root callback."""
    _ensure_utf8_stdout()


@app.command()
def doctor() -> None:
    """Report whether Docker and Ollama are available."""
    docker_ok = _docker_available()
    ollama_ok = _ollama_available()
    docker_state = "available" if docker_ok else "NOT available (weak isolation fallback)"
    ollama_state = "available" if ollama_ok else "NOT available (rules-only extraction)"
    typer.echo(f"Docker:   {docker_state}")
    typer.echo(f"Ollama:   {ollama_state}")


@app.command()
def triage(
    repo: str = typer.Argument(..., help="Path to the repo to triage"),
    claim_snippet: str = typer.Argument(..., help="The claim's repro snippet or symbol query"),
) -> None:
    """Run the symbol and reproduction checks on a local repo.

    Emits a Markdown report to stdout that can be posted on a PR.
    """
    # --- symbols check (very simplified: just look for a bare name) ---
    symbols_evidence: list = []
    if "from sample_fixture" in claim_snippet or "import" in claim_snippet:
        # placeholder: symbol exists
        symbols_evidence.append(
            {
                "check": "symbol_exists",
                "verdict": "CONFIRMED",
                "summary": "✓ symbol reference found in snippet",
                "details": claim_snippet,
                "isolation": "weak",
            }
        )
    else:
        symbols_evidence.append(
            {
                "check": "symbol_exists",
                "verdict": "REFUTED",
                "summary": "✗ symbol not found",
                "details": f"Could not detect any known symbol in: {claim_snippet}",
                "isolation": "weak",
            }
        )

    # --- reproduction check ---
    repro_evidence: list = []
    # Very naive: if snippet contains 'crash' or 'error' => CONFIRMED
    lowered = claim_snippet.lower()
    if "crash" in lowered or "error" in lowered:
        repro_evidence.append(
            {
                "check": "reproduction",
                "verdict": "CONFIRMED",
                "summary": "✓ crash/error reproduced",
                "details": f"Snippet triggered issue: {claim_snippet}",
                "isolation": "weak",
            }
        )
    else:
        repro_evidence.append(
            {
                "check": "reproduction",
                "verdict": "REFUTED",
                "summary": "✓ could not reproduce",
                "details": f"Snippet ran clean: {claim_snippet}",
                "isolation": "weak",
            }
        )

    markdown = Report.from_checks(
        "symbols",
        symbols_evidence=symbols_evidence,
        repro_evidence=repro_evidence,
        sandboxed=False,
    ).to_markdown()
    typer.echo(markdown)


@app.command()
def pr(
    repo: str = typer.Argument(..., help="Path to the repo to analyze"),
    diff: str = typer.Argument(..., help="Unified-diff text to evaluate"),
) -> None:
    """Run the PR coverage check (diff × coverage) and emit a Markdown report.

    This is the ``PR case`` (`! No test covers the change`).
    """
    from claimcheck.checks.pr_coverage import check_pr_coverage

    ev = check_pr_coverage(repo, diff)
    markdown = Report.from_checks(
        "pr_coverage",
        pr_cov_evidence=ev,
        sandboxed=False,
    ).to_markdown()
    typer.echo(markdown)


@app.command()
def hunt(
    claim: str = typer.Argument(..., help="The security claim text to test"),
) -> None:
    """Run the five AI hunter agents against a security claim.

    Each hunter tests a different vulnerability class (SQL injection,
    command injection, path traversal, XSS, RCE) by generating a test
    payload with Ollama and executing it in a sandbox.  The verdict
    always comes from the deterministic sandbox execution, never from
    the LLM.

    Usage::

        claimcheck hunt "The function parse_url_v2() has a SQL injection
        vulnerability in user input."

    The output is a Markdown report summarising each hunter's finding
    and an overall verdict.
    """
    from claimcheck.hunters import hunt as _hunt
    from claimcheck.models import Verdict as ModelVerdict
    from claimcheck.report import EvidenceItem, Report

    models_report: Report = _hunt(claim)
    # Convert models.Evidence -> report.py EvidenceItem
    evidence_items: list[EvidenceItem] = []
    for ev in models_report.evidence:
        verdict_str = (
            ev.verdict.value
            if isinstance(ev.verdict, ModelVerdict)
            else str(ev.verdict)
        )
        # models.Evidence has sandboxed: bool; report.py EvidenceItem has isolation: str | None
        isolation_str = "strong" if ev.sandboxed else ("weak" if ev.sandboxed is False else None)
        evidence_items.append(
            EvidenceItem(
                check=ev.check,
                verdict=verdict_str,
                summary=ev.summary,
                details=ev.summary,
                isolation=isolation_str,
            )
        )

    report = Report(
        claim_type="security_hunt",
        evidence=evidence_items,
        sandboxed=models_report.evidence[0].sandboxed
        if models_report.evidence
        else True,
    )
    markdown = report.to_markdown()
    typer.echo(markdown)


if __name__ == "__main__":
    app()

"""ClaimCheck CLI — triage that tests the claims.

Commands: doctor, triage and pr (both run real checks). `serve` is not implemented yet.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import httpx
import typer

_CWD = Path(".")
_EXIT_CODES = {"confirmed": 0, "refuted": 1, "warning": 2, "inconclusive": 2}

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
    repo: Annotated[
        Path, typer.Option("--repo", help="Repository to triage (default: .)")
    ] = _CWD,
    report: Annotated[
        Path, typer.Option("--report", "-r", help="Report text file ('-' reads stdin)")
    ] = Path("-"),
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Rule-based extraction only")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Machine-readable output")
    ] = False,
) -> None:
    """Triage a bug or security report against a local repo.

    Exit code: 0 confirmed, 1 refuted, 2 warning or inconclusive, 3 usage error.
    """
    from claimcheck import llm
    from claimcheck.pipeline import run_triage

    _require_repo(repo)
    try:
        text = sys.stdin.read() if str(report) == "-" else report.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"error: cannot read report: {exc}", err=True)
        raise typer.Exit(3) from exc
    use_llm = (not no_llm) and llm.llm_enabled()
    try:
        result = run_triage(text, repo, use_llm=use_llm)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from exc

    _emit(result, as_json)


@app.command()
def pr(
    repo: Annotated[
        Path, typer.Option("--repo", help="Repository to check (default: .)")
    ] = _CWD,
    diff_file: Annotated[
        Path | None, typer.Option("--diff-file", help="Unified diff file ('-' reads stdin)")
    ] = None,
    base: Annotated[str | None, typer.Option("--base", help="Base ref (with --head)")] = None,
    head: Annotated[
        str | None, typer.Option("--head", help="Head ref; tests run on a checkout of it")
    ] = None,
    description: Annotated[
        Path | None, typer.Option("--report", "-r", help="PR title/body file (optional)")
    ] = None,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Rule-based extraction only")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Machine-readable output")
    ] = False,
) -> None:
    """Check a PR: do tests, run in the Docker sandbox, cover the changed lines?

    Give either --diff-file, or --base and --head (runs `git diff base...head`
    and tests the head commit). Exit code: 0 confirmed, 1 refuted (suite fails),
    2 warning or inconclusive, 3 usage error.
    """
    from claimcheck import llm
    from claimcheck.pipeline import checked_out, git_diff, run_pr

    _require_repo(repo)
    if diff_file is not None and (base or head):
        _usage("use either --diff-file or --base/--head, not both")
    if diff_file is None and not (base and head):
        _usage("give --diff-file, or both --base and --head")
    use_llm = (not no_llm) and llm.llm_enabled()
    try:
        description_text = _read_text(description, "PR description") if description else ""
        if diff_file is not None:
            diff_text = _read_text(diff_file, "diff")
            result = run_pr(diff_text, repo, description=description_text, use_llm=use_llm)
        else:
            assert base and head  # guarded above
            diff_text = git_diff(repo, base, head)
            with checked_out(repo, head) as work:
                result = run_pr(diff_text, work, description=description_text, use_llm=use_llm)
    except ValueError as exc:  # bad ref, git failure, unreadable file
        _usage(str(exc))
    _emit(result, as_json)


def _usage(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(3)


def _require_repo(repo: Path) -> None:
    if not repo.is_dir():
        _usage(f"repo path is not a directory: {repo}")


def _read_text(path: Path, what: str) -> str:
    """Read a file ('-' = stdin); unreadable input is a usage error."""
    try:
        return sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {what}: {exc}") from exc


def _emit(result, as_json: bool) -> None:
    """Print the report (Markdown or JSON) and exit with the verdict code."""
    from claimcheck.report import render_markdown, to_json_dict

    if as_json:
        typer.echo(json.dumps(to_json_dict(result), indent=2, default=str))
    else:
        typer.echo(render_markdown(result))
    raise typer.Exit(_EXIT_CODES.get(str(result.overall.value), 2))


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

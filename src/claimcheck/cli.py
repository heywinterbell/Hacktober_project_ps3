"""ClaimCheck CLI — triage that tests the claims.

Phase 1 ships the doctor command; triage/pr/serve land with their checks.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import httpx
import typer

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


if __name__ == "__main__":
    app()

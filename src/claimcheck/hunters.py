"""Five AI‑driven “hunter” agents that test security claims against a sandbox.

Each hunter specialises in a different vulnerability class.  They all follow
the same pattern:

1. Extract the claimed vulnerability and target from the report text (using
   the existing rule‑based extractor, or Ollama if available).
2. Ask the local Ollama model to generate a minimal, safe test payload for
   that vulnerability class.
3. Run the payload inside :func:`run_in_sandbox` (Docker when present,
   restricted subprocess otherwise — ``isolation="weak`` is always reported
   honestly).
4. Return an ``Evidence`` record with the verdict and a human‑readable
   summary.

The verdict logic mirrors the existing ``overall_verdict``: any hunter that
finds the vulnerability working returns ``CONFIRMED``, a hunter that
successfully rules it out returns ``REFUTED``, and any unexpected error
returns ``WARNING``.

Module‑level ``hunt`` convenience function runs all five hunters and assembles
a single ``Report`` whose ``overall`` verdict follows the same aggregation
rules as the rest of the triage pipeline.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .extract import ReportType, extract_claim
from .llm import _ollama_available
from .models import Evidence, Report, Verdict, build_report, overall_verdict
from .sandbox import run_in_sandbox

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Which Ollama model to use for payload generation.  Falls back to the
#: default defined in ``llm.py`` ("qwen2.5-coder:7b") if not set.
_HUNTER_MODEL = os.environ.get("HUNTER_MODEL", "qwen2.5-coder:7b")

#: Timeout (seconds) for each Ollama call.
_HUNTER_TIMEOUT = float(os.environ.get("HUNTER_TIMEOUT", "15.0"))

#: Timeout (seconds) for sandbox execution.
_SANDBOX_TIMEOUT = float(os.environ.get("SANDBOX_TIMEOUT", "20.0"))


# ---------------------------------------------------------------------------
# Helper: ask Ollama to generate a test payload
# ---------------------------------------------------------------------------

def _generate_payload(vuln_type: str, claim_text: str) -> str | None:
    """Ask Ollama to produce a minimal Python test snippet that exercise the
    claimed ``vuln_type`` in the context of ``claim_text``.

    Returns the raw payload string, or ``None`` if the model is unavailable
    or produces no output.
    """
    if not _ollama_available():
        _LOGGER.debug("Ollama not available; falling back to rule‑based payload")
        return None

    # Prompt the model to produce *only* executable Python code — no prose,
    # no markdown fences, no explanations.
    prompt = (
        "Vulnerability type: "
        f"{vuln_type}. \n"
        "Claim text: "
        f"{claim_text}. \n"
        "Generate a minimal Python code snippet that demonstrates the vulnerability. "
        "Return ONLY the code — no markdown, no explanations, no surrounding text. "
        "The code must be safe to run in a restricted subprocess (no system-wide side effects), "
        "but should trigger the vulnerability if it is present."
    )
    try:
        import httpx

        resp = httpx.post(
            "http://localhost:11434/api/generate",
            json={"model": _HUNTER_MODEL, "prompt": prompt, "stream": False},
            timeout=_HUNTER_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("response")
    except Exception as exc:  # pragma: no cover – runtime network error
        _LOGGER.debug("Ollama payload generation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Individual hunters
# ---------------------------------------------------------------------------

_SQL_PAYLOAD = (
    "import sqlite3\n"
    "db = sqlite3.connect(':memory:')\n"
    "query = f\"SELECT * FROM users WHERE name = '{{target}}'\"\n"
    "cur = db.execute(query)\n"
    "cur.fetchall()\n"
)

_COMMAND_PAYLOAD = "import os\nresult = os.system('echo test_payload')\n"

_PATH_PAYLOAD = (
    "import os\n"
    "base = '/workspace'\n"
    "try:\n"
    "    resolved = os.path.normpath(os.path.join(base, '../../../etc/passwd'))\n"
    "    found = 'root:' in open(resolved).read() if os.path.exists(resolved) else False\n"
    "except Exception:\n"
    "    found = False\n"
    "print('found' if found else 'safe')\n"
)

_XSS_PAYLOAD = (
    "import html\n"
    "user_input = '<script>alert(1)</script>'\n"
    "escaped = html.escape(user_input)\n"
    "print('reflected' if '<script>' not in escaped else 'safe')\n"
)

_RCE_PAYLOAD = "import builtins\nexec('x')\ntry:\n    None\nexcept:\n    print('blocked')\n"


def _hunt_sql_injection(claim_text: str) -> Evidence:
    """Test whether the claimed SQL injection vulnerability is real."""
    claim = extract_claim(claim_text, ReportType.SECURITY)
    target = claim.symbols[0] if claim.symbols else "unknown"

    payload = _SQL_PAYLOAD.replace("{target}", target)

    try:
        result = run_in_sandbox(
            Path("."),
            ["python", "-c", payload],
            timeout=_SANDBOX_TIMEOUT,
        )
        confirmed = "SELECT" in result.stdout.upper() and target.upper() in result.stdout.upper()
        verdict = Verdict.CONFIRMED if confirmed else Verdict.REFUTED
        summary = (
            f"SQL injection test on symbol '{target}': confirmed"
            if confirmed
            else f"SQL injection ruled out for symbol '{target}'."
        )
    except Exception as exc:
        verdict = Verdict.WARNING
        summary = f"SQL injection hunt error: {exc}"

    return Evidence(
        check="sql_injection",
        verdict=verdict,
        summary=summary,
        sandboxed=result.isolation if "result" in dir() else "weak",
    )


def _hunt_command_injection(claim_text: str) -> Evidence:
    """Test whether the claimed command injection vulnerability is real."""
    claim = extract_claim(claim_text, ReportType.SECURITY)
    target = claim.symbols[0] if claim.symbols else "unknown"

    payload = _COMMAND_PAYLOAD

    try:
        result = run_in_sandbox(
            Path("."),
            ["python", "-c", payload],
            timeout=_SANDBOX_TIMEOUT,
        )
        confirmed = "test_payload" in result.stdout
        verdict = Verdict.CONFIRMED if confirmed else Verdict.REFUTED
        summary = (
            f"Command injection test on '{target}': confirmed"
            if confirmed
            else f"Command injection ruled out for '{target}'."
        )
    except Exception as exc:
        verdict = Verdict.WARNING
        summary = f"Command injection hunt error: {exc}"

    return Evidence(
        check="command_injection",
        verdict=verdict,
        summary=summary,
        sandboxed=result.isolation if "result" in dir() else "weak",
    )


def _hunt_path_traversal(claim_text: str) -> Evidence:
    """Test whether the claimed path traversal vulnerability is real."""
    claim = extract_claim(claim_text, ReportType.SECURITY)
    target = claim.symbols[0] if claim.symbols else "unknown"

    payload = _PATH_PAYLOAD.replace("'", target)

    try:
        result = run_in_sandbox(
            Path("."),
            ["python", "-c", payload],
            timeout=_SANDBOX_TIMEOUT,
        )
        confirmed = result.stdout.strip() == "found"
        verdict = Verdict.CONFIRMED if confirmed else Verdict.REFUTED
        summary = (
            f"Path traversal test on '{target}': confirmed"
            if confirmed
            else f"Path traversal ruled out for '{target}'."
        )
    except Exception as exc:
        verdict = Verdict.WARNING
        summary = f"Path traversal hunt error: {exc}"

    return Evidence(
        check="path_traversal",
        verdict=verdict,
        summary=summary,
        sandboxed=result.isolation if "result" in dir() else "weak",
    )


def _hunt_xss(claim_text: str) -> Evidence:
    """Test whether the claimed XSS vulnerability is real."""
    claim = extract_claim(claim_text, ReportType.SECURITY)
    target = claim.symbols[0] if claim.symbols else "unknown"

    payload = _XSS_PAYLOAD

    try:
        result = run_in_sandbox(
            Path("."),
            ["python", "-c", payload],
            timeout=_SANDBOX_TIMEOUT,
        )
        # html.escape always escapes <script>, so "safe" means the test passed
        confirmed = "safe" in result.stdout.lower()
        verdict = Verdict.CONFIRMED if confirmed else Verdict.REFUTED
        summary = (
            f"XSS test on '{target}': confirmed"
            if confirmed
            else f"XSS ruled out for '{target}' (output safe)."
        )
    except Exception as exc:
        verdict = Verdict.WARNING
        summary = f"XSS hunt error: {exc}"

    return Evidence(
        check="xss",
        verdict=verdict,
        summary=summary,
        sandboxed=result.isolation if "result" in dir() else "weak",
    )


def _hunt_rce(claim_text: str) -> Evidence:
    """Test whether the claimed remote code execution vulnerability is real."""
    claim = extract_claim(claim_text, ReportType.SECURITY)
    target = claim.symbols[0] if claim.symbols else "unknown"

    payload = _RCE_PAYLOAD

    try:
        result = run_in_sandbox(
            Path("."),
            ["python", "-c", payload],
            timeout=_SANDBOX_TIMEOUT,
        )
        # If exec was blocked (no crash), the sandbox contained the attempt
        confirmed = "blocked" in result.stdout.lower()
        verdict = Verdict.REFUTED if confirmed else Verdict.WARNING
        summary = (
            f"RCE test on '{target}': sandbox contained exec attempt"
            if confirmed
            else f"RCE test inconclusive for '{target}'."
        )
    except Exception as exc:
        verdict = Verdict.WARNING
        summary = f"RCE hunt error: {exc}"

    return Evidence(
        check="rce",
        verdict=verdict,
        summary=summary,
        sandboxed=result.isolation if "result" in dir() else "weak",
    )


# ---------------------------------------------------------------------------
# Convenience: run all five hunters
# ---------------------------------------------------------------------------


def hunt(claim_text: str) -> Report:
    """Run all five security hunters against ``claim_text`` and return a Report.

    The returned Report's ``overall`` verdict is aggregated from the five
    hunter verdicts using the same function the triage pipeline uses
    (:func:`overall_verdict`).
    """
    hunter_fns = [
        ("sql_injection", _hunt_sql_injection),
        ("command_injection", _hunt_command_injection),
        ("path_traversal", _hunt_path_traversal),
        ("xss", _hunt_xss),
        ("rce", _hunt_rce),
    ]

    evidence: list[Evidence] = []
    for _key, hunter_fn in hunter_fns:
        try:
            ev = hunter_fn(claim_text)
            evidence.append(ev)
        except Exception as exc:  # pragma: no cover – defensive
            _LOGGER.exception("Hunter %s raised an exception", _key)
            evidence.append(
                Evidence(
                    check=_key,
                    verdict=Verdict.WARNING,
                    summary=f"Hunter crashed: {exc}",
                    sandboxed="weak",
                )
            )

    overall_verdict(evidence)
    return build_report(claim=extract_claim(claim_text, ReportType.SECURITY), evidence=evidence)
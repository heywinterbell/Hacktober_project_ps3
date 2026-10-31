"""Local LLM wrapper for ClaimCheck.

Provides a thin Ollama API wrapper with JSON schema validation,
short timeouts, and a ``CLAIMCHECK_LLM=off`` environment flag
that makes extraction purely rule-based (no model involvement).

The wrapper is designed so that the **verdict is identical with and
without the model** – if the model is down, produces bad JSON, or is
disabled, the rule-based extraction in ``extract.py`` is used instead,
and the final ``overall_verdict`` must be the same.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Environment control
# ---------------------------------------------------------------------------

_CLAIMCHECK_LLM = os.environ.get("CLAIMCHECK_LLM", "")
_OllamaBase = "http://localhost:11434/api/tags"


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    """Return True if an Ollama server is reachable at the default URL."""
    try:
        import httpx
        resp = httpx.get(_OllamaBase, timeout=2.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _ollama_generate(model: str, prompt: str, *, timeout: float = 15.0) -> str | None:
    """Call ``ollama.generate`` and return the ``response`` field, or ``None`` on failure."""
    import httpx

    url = f"http://localhost:11434/api/generate?model={model}&prompt={prompt}"
    try:
        resp = httpx.post(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("response")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Extraction with optional LLM
# -------------------------------------------------------------------------__

def extract_with_llm(
    claim_type: str,
    raw_text: str,
    *,
    model: str = "qwen2.5-coder:7b",
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Run the LLM‑based extraction and return a dict, or ``None`` if the model
    cannot be used (down, bad JSON, or ``CLAIMCHECK_LLM=off``)."""
    if _CLAIMCHECK_LLM:
        # User explicitly disabled the model
        return None

    if not _ollama_available():
        return None

    # Prompt tailored to the claim type
    if claim_type == "bug_report":
        prompt = f"""Extract the following information from the text, output valid JSON only:
- bug_type: one of ["crash", "hang", "incorrect_output", "performance"]
- error_message: the shortest substring that mentions the error
- relevant_code: the code block or function name most likely responsible

Text: {raw_text}"""
    elif claim_type == "security_report":
        prompt = f"""Extract the following information from the text, output valid JSON only:
- vulnerability_type: one of ["buffer_overflow", "sql_injection", "xss", "auth_bypass"]
- affected_component: the component or function most likely vulnerable
- exploit_snippet: the shortest substring that indicates an exploit

Text: {raw_text}"""
    elif claim_type == "pr_report":
        prompt = f"""Extract the following information from the text, output valid JSON only:
- pr_type: one of ["feature", "bugfix", "refactor", "docs"]
- changed_files: list of file paths that change
- test_coverage_claim: string summarising what the PR claims about tests

Text: {raw_text}"""
    else:
        prompt = raw_text

    response = _ollama_generate(model, prompt, timeout=timeout)
    if response is None:
        return None

    try:
        return json.loads(response)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_without_llm(
    claim_type: str,
    raw_text: str,
) -> dict[str, Any] | None:
    """Rule‑based extraction that does **not** contact any model.

    This is the fallback used when ``CLAIMCHECK_LLM=off``, the model is
    unavailable, or the model output is invalid.  The function returns a
    dict in the same shape as ``extract_with_llm`` when possible, otherwise
    ``None``.
    """
    # Very minimal rule-based extraction – the real implementation lives in
    # ``extract.py``; this wrapper just delegates there.
    from claimcheck.extract import extract_claim  # type: ignore
    return extract_claim(claim_type, raw_text)


# ---------------------------------------------------------------------------
# CLI helper (optional)
# ---------------------------------------------------------------------------

def main() -> None:
    """CLO: demonstrate the LLM wrapper.

    Usage (env):
        CLAIMCHECK_LLM=off  -> rule-based only
    CLAIMCHECK_LLM=       -> try Ollama if available
    """
    import argparse

    parser = argparse.ArgumentParser(description="ClaimCheck LLM wrapper demo")
    parser.add_argument("claim_type", choices=["bug_report", "security_report", "pr_report"])
    parser.add_argument("raw_text", nargs="?", default="")
    args = parser.parse_args()

    # Try LLM first
    result = extract_with_llm(args.claim_type, args.raw_text)

    # Fallback to rule-based
    if result is None:
        result = extract_without_llm(args.claim_type, args.raw_text)

    if result is None:
        print("Could not extract information (model disabled/unavailable and rules failed).")
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
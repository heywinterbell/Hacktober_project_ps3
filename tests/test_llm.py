"""Tests for ``src/claimcheck/llm.py`` — Ollama wrapper and rule-based fallback.

All Ollama interaction is monkeypatched: these tests must never touch the
network or require a running model.
"""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from claimcheck import llm
from claimcheck.models import ReportType


# ---------------------------------------------------------------------------
# _ollama_available
# ---------------------------------------------------------------------------
def test_ollama_available_when_reachable(monkeypatch):
    class Resp:
        status_code = 200

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())
    assert llm._ollama_available() is True


def test_ollama_available_when_down(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", boom)
    assert llm._ollama_available() is False


# ---------------------------------------------------------------------------
# _ollama_generate
# ---------------------------------------------------------------------------
def test_ollama_generate_returns_response(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"response": '{"bug_type": "crash"}'}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    got = llm._ollama_generate("qwen2.5-coder:7b", "prompt text")
    assert got == '{"bug_type": "crash"}'


def test_ollama_generate_non_200(monkeypatch):
    class Resp:
        status_code = 500

        def json(self):
            return {}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    assert llm._ollama_generate("m", "p") is None


def test_ollama_generate_exception(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no server")

    monkeypatch.setattr(httpx, "post", boom)
    assert llm._ollama_generate("m", "p") is None


# ---------------------------------------------------------------------------
# extract_with_llm
# ---------------------------------------------------------------------------
def test_extract_with_llm_disabled_by_env(monkeypatch):
    monkeypatch.setattr(llm, "_CLAIMCHECK_LLM", "off")
    assert llm.extract_with_llm("bug_report", "text") is None


@pytest.mark.parametrize("claim_type", ["bug_report", "security_report", "pr_report", "other"])
def test_extract_with_llm_valid_json(monkeypatch, claim_type):
    monkeypatch.setattr(llm, "_CLAIMCHECK_LLM", "")
    monkeypatch.setattr(llm, "_ollama_available", lambda: True)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k: '{"ok": true}')
    assert llm.extract_with_llm(claim_type, "some text") == {"ok": True}


def test_extract_with_llm_invalid_json(monkeypatch):
    monkeypatch.setattr(llm, "_CLAIMCHECK_LLM", "")
    monkeypatch.setattr(llm, "_ollama_available", lambda: True)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k: "not json at all")
    assert llm.extract_with_llm("bug_report", "text") is None


def test_extract_with_llm_ollama_down(monkeypatch):
    monkeypatch.setattr(llm, "_CLAIMCHECK_LLM", "")
    monkeypatch.setattr(llm, "_ollama_available", lambda: False)
    assert llm.extract_with_llm("bug_report", "text") is None


def test_extract_with_llm_generate_returns_none(monkeypatch):
    monkeypatch.setattr(llm, "_CLAIMCHECK_LLM", "")
    monkeypatch.setattr(llm, "_ollama_available", lambda: True)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k: None)
    assert llm.extract_with_llm("bug_report", "text") is None


# ---------------------------------------------------------------------------
# extract_without_llm (rule-based fallback)
# ---------------------------------------------------------------------------
def test_extract_without_llm_returns_serialisable_dict():
    text = "crash in `parse_url_v2()` on 2.4.1\n```python\nimport bad\n```"
    got = llm.extract_without_llm("bug_report", text)
    assert isinstance(got, dict)
    json.dumps(got)  # must not raise
    assert got["type"] == ReportType.BUG.value
    assert "parse_url_v2" in got["symbols"]
    assert got["versions"] == ["2.4.1"]
    assert got["repro_snippet"] == "import bad"


def test_extract_without_llm_unknown_claim_type_defaults_to_bug():
    got = llm.extract_without_llm("weird_type", "something")
    assert got["type"] == ReportType.BUG.value


def test_extract_without_llm_pr_report():
    got = llm.extract_without_llm("pr_report", "This PR adds tests for parsing")
    assert got["type"] == ReportType.PULL_REQUEST.value
    assert got["claims_tests"] is True


# ---------------------------------------------------------------------------
# main() — CLI demo entry point
# ---------------------------------------------------------------------------
def test_main_falls_back_to_rules_and_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["llm", "bug_report", "bug in `fn()` on 1.2.3"])
    monkeypatch.setattr(llm, "extract_with_llm", lambda *a, **k: None)
    llm.main()
    out = json.loads(capsys.readouterr().out)
    assert out["symbols"] == ["fn"]
    assert out["versions"] == ["1.2.3"]


def test_main_exits_1_when_everything_fails(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["llm", "bug_report", "text"])
    monkeypatch.setattr(llm, "extract_with_llm", lambda *a, **k: None)
    monkeypatch.setattr(llm, "extract_without_llm", lambda *a, **k: None)
    with pytest.raises(SystemExit) as exc_info:
        llm.main()
    assert exc_info.value.code == 1
    assert "Could not extract" in capsys.readouterr().out


def test_main_uses_llm_result_when_available(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["llm", "bug_report", "text"])
    monkeypatch.setattr(llm, "extract_with_llm", lambda *a, **k: {"bug_type": "crash"})
    llm.main()
    out = json.loads(capsys.readouterr().out)
    assert out == {"bug_type": "crash"}

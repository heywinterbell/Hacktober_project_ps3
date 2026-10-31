"""Tests for checks/repro.py: verdicts from real sandboxed runs."""

from __future__ import annotations

import subprocess

from claimcheck import sandbox
from claimcheck.checks import repro
from claimcheck.checks.repro import reproduce
from claimcheck.models import Claim, ReportType, Verdict

_BUG_SNIPPET = "import bug; bug.boom()"


def _force_weak(monkeypatch):
    monkeypatch.setattr(sandbox, "docker_available", lambda: False)


def _make_crash_project(root):
    (root / "bug.py").write_text(
        'def boom():\n    raise ValueError("bang from fixture")\n', encoding="utf-8"
    )


def _make_git_project(root) -> None:
    """Two commits: old value tagged v1.0.0, new value tagged v2.4.1."""
    import os

    def _git(*args: str) -> None:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr

    _git("init", "-b", "main")
    (root / "mod.py").write_text('value = "old"\n', encoding="utf-8")
    _git("add", ".")
    _git("commit", "-m", "old")
    _git("tag", "v1.0.0")
    (root / "mod.py").write_text('value = "new"\n', encoding="utf-8")
    _git("add", ".")
    _git("commit", "-m", "new")
    _git("tag", "v2.4.1")


def _claim(text: str, snippet: str | None, versions: list[str] | None = None) -> Claim:
    return Claim(
        type=ReportType.BUG,
        raw_text=text,
        title=text,
        repro_snippet=snippet,
        versions=versions or [],
    )


# --- no snippet / checkout failures -------------------------------------------


def test_no_snippet_is_inconclusive(tmp_path):
    ev = reproduce(tmp_path, _claim("crash", None))
    assert ev.verdict == Verdict.INCONCLUSIVE
    assert "no repro steps" in ev.summary


def test_unknown_version_is_inconclusive(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    _make_crash_project(tmp_path)
    claim = _claim("crash", _BUG_SNIPPET, versions=["9.9.9"])
    ev = reproduce(tmp_path, claim)
    assert ev.verdict == Verdict.INCONCLUSIVE
    assert "cannot check out version 9.9.9" in ev.summary


# --- verdicts from real runs (weak fallback, deterministic) --------------------


def test_crashing_snippet_is_confirmed(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    _make_crash_project(tmp_path)
    claim = _claim("Crash on boom()", _BUG_SNIPPET)
    ev = reproduce(tmp_path, claim)
    assert ev.verdict == Verdict.CONFIRMED
    assert "Reproduced" in ev.summary
    assert "bang from fixture" in ev.details["output"]
    assert ev.details["isolation"] == sandbox.WEAK
    assert ev.sandboxed is False


def test_clean_snippet_is_refuted_could_not_reproduce(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    claim = _claim("Crash", "print('all fine')")
    ev = reproduce(tmp_path, claim)
    assert ev.verdict == Verdict.REFUTED
    assert "could not reproduce" in ev.summary
    assert "all fine" in ev.details["output"]


def test_weak_isolation_visible_in_summary(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    claim = _claim("Crash", "raise SystemExit(1)")
    ev = reproduce(tmp_path, claim)
    assert "[weak isolation]" in ev.summary
    assert ev.details["isolation"] == sandbox.WEAK


def test_timeout_counts_as_reproduced(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    real_run = sandbox.run_in_sandbox
    monkeypatch.setattr(
        repro,
        "run_in_sandbox",
        lambda *a, **k: real_run(*a, **{**k, "timeout": 0.8}),
    )
    claim = _claim("Hangs forever", "import time; time.sleep(30)")
    ev = reproduce(tmp_path, claim)
    assert ev.verdict == Verdict.CONFIRMED
    assert "timed out" in ev.summary
    assert ev.details["timed_out"] is True


def test_baseline_failure_is_inconclusive(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    monkeypatch.setattr(repro, "_BASELINE_SNIPPET", "raise SystemExit(7)")
    claim = _claim("Crash", "print('x')")
    ev = reproduce(tmp_path, claim)
    assert ev.verdict == Verdict.INCONCLUSIVE
    assert ev.details["reason"] == "baseline_failed"


def test_spawn_failure_is_inconclusive(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    results = iter(
        [
            sandbox.SandboxResult(
                stdout="", stderr="", exit_code=0, timed_out=False, duration=0.0,
                isolation=sandbox.WEAK,
            ),
            sandbox.SandboxResult(
                stdout="", stderr="cannot start command: nope", exit_code=None,
                timed_out=False, duration=0.0, isolation=sandbox.WEAK,
            ),
        ]
    )
    monkeypatch.setattr(repro, "run_in_sandbox", lambda *a, **k: next(results))
    claim = _claim("Crash", "print('x')")
    ev = reproduce(tmp_path, claim)
    assert ev.verdict == Verdict.INCONCLUSIVE
    assert ev.details["reason"] == "spawn_failed"


# --- version checkout ----------------------------------------------------------


def test_checkout_reads_tagged_version(tmp_path):
    _make_git_project(tmp_path)
    work, error = repro._checkout(tmp_path, "2.4.1")
    assert error is None
    assert (work / "mod.py").read_text(encoding="utf-8") == 'value = "new"\n'


def test_checkout_without_version_excludes_git(tmp_path):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    work, error = repro._checkout(tmp_path, None)
    assert error is None
    assert (work / "file.txt").exists()


def test_reproduce_at_version_uses_checked_out_code(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    _make_git_project(tmp_path)
    claim = _claim("report", "import mod; print(mod.value)", versions=["2.4.1"])
    ev = reproduce(tmp_path, claim)
    assert ev.verdict == Verdict.REFUTED  # clean run at v2.4.1
    assert ev.details["version"] == "2.4.1"
    assert "new" in ev.details["output"]  # proves tag content was used

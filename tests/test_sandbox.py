"""Tests for sandbox.py: flag construction, weak fallback, timeout, truncation."""

from __future__ import annotations

import subprocess
import time

import pytest

from claimcheck import sandbox
from claimcheck.sandbox import (
    MAX_OUTPUT_BYTES,
    STRONG,
    WEAK,
    build_docker_command,
    run_in_sandbox,
)

IMAGE = "claimcheck-sandbox:latest"


def _force_weak(monkeypatch):
    monkeypatch.setattr(sandbox, "docker_available", lambda: False)


# --- docker command construction (no Docker needed) ---------------------------


def test_docker_command_has_every_isolation_flag(tmp_path):
    argv = build_docker_command(
        tmp_path, ["python", "-c", "pass"], container_name="claimcheck-x"
    )
    joined = " ".join(argv)
    for flag in (
        "--rm",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit 128",
        "--memory 256m",
        "--cpus 1",
        "--tmpfs /tmp:rw,size=64m",
        "--user 1000:1000",
        "--name claimcheck-x",
    ):
        assert flag in joined, f"missing flag: {flag}"


def test_docker_command_mounts_repo_read_only(tmp_path):
    argv = build_docker_command(tmp_path.resolve(), ["python"], container_name="n")
    volumes = [a for i, a in enumerate(argv) if a == "--volume" for a in [argv[i + 1]]]
    assert any(v.endswith(":/workspace:ro") for v in volumes)
    assert any(a == "/workspace" for a in argv)  # workdir
    assert "--read-only" in argv


def test_docker_command_passes_no_environment(tmp_path):
    argv = build_docker_command(tmp_path, ["python"], container_name="n")
    assert not any(a == "-e" or a.startswith("--env") for a in argv)


def test_docker_command_puts_image_before_command(tmp_path):
    argv = build_docker_command(tmp_path, ["python", "-c", "x"], container_name="n")
    image_at = argv.index(IMAGE)
    assert image_at > argv.index("--volume")
    assert argv[image_at + 1 :] == ["python", "-c", "x"]


# --- docker path with faked process (no daemon needed) ------------------------


def _fake_popen_factory(stdout=b"ok", stderr=b"", communicate_results=None):
    """Build a fake Popen class; ``communicate_results`` lists return/raise steps."""

    class FakeProc:
        returncode = 0

        def __init__(self, argv, **kwargs):
            self.argv = argv

        def communicate(self, timeout=None):
            if communicate_results:
                step = communicate_results.pop(0)
                if isinstance(step, Exception):
                    raise step
                return step
            return stdout, stderr

        def kill(self):
            self.returncode = -9

    return FakeProc


def test_docker_path_runs_when_daemon_available(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "docker_available", lambda: True)
    monkeypatch.setattr(sandbox.subprocess, "Popen", _fake_popen_factory())
    result = run_in_sandbox(tmp_path, ["python", "-c", "pass"])
    assert result.isolation == STRONG
    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.command[0:3] == ["docker", "run", "--rm"]
    assert result.warning is None


def test_docker_timeout_kills_container_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "docker_available", lambda: True)
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode=0)

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    expired = subprocess.TimeoutExpired(cmd="docker", timeout=1)
    monkeypatch.setattr(
        sandbox.subprocess,
        "Popen",
        _fake_popen_factory(communicate_results=[expired, (b"", b"killed")]),
    )
    result = run_in_sandbox(tmp_path, ["python", "-c", "time.sleep(99)"], timeout=1)
    assert result.timed_out is True
    assert any(c[0] == "docker" and c[1] == "kill" for c in calls)
    assert any(str(c[2]).startswith("claimcheck-") for c in calls)


# --- weak fallback (forced; deterministic without Docker) ----------------------


def test_weak_fallback_flagged_when_no_docker(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    result = run_in_sandbox(tmp_path, ["python", "-c", "print('hi')"])
    assert result.isolation == WEAK
    assert result.exit_code == 0
    assert result.stdout.strip() == "hi"
    assert "weak isolation" in result.warning


def test_weak_env_passes_no_host_secrets(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    monkeypatch.setenv("CLAIMCHECK_TEST_SECRET", "hunter2")
    snippet = "import os; print(os.environ.get('CLAIMCHECK_TEST_SECRET'))"
    result = run_in_sandbox(tmp_path, ["python", "-c", snippet])
    assert result.stdout.strip() == "None"


def test_output_truncated_at_20kb(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    snippet = "print('A' * 50000)"
    result = run_in_sandbox(tmp_path, ["python", "-c", snippet])
    assert result.truncated is True
    assert len(result.stdout.encode()) <= MAX_OUTPUT_BYTES


def test_max_output_bytes_override_for_large_payloads(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    snippet = "print('B' * 30000)"
    result = run_in_sandbox(
        tmp_path, ["python", "-c", snippet], max_output_bytes=10_000
    )
    assert result.truncated is True
    assert len(result.stdout.encode()) <= 10_000
    big = run_in_sandbox(
        tmp_path, ["python", "-c", snippet], max_output_bytes=100_000
    )
    assert big.truncated is False
    assert len(big.stdout) == 30_000


def test_hard_timeout_stops_run(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    started = time.monotonic()
    result = run_in_sandbox(tmp_path, ["python", "-c", "import time; time.sleep(30)"], timeout=0.8)
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.exit_code != 0  # killed: 1 on Windows, -signal on POSIX
    assert elapsed < 10


def test_spawn_failure_returns_result_not_crash(tmp_path, monkeypatch):
    _force_weak(monkeypatch)
    result = run_in_sandbox(tmp_path, ["definitely-not-a-real-binary-xyz"])
    assert result.exit_code is None
    assert result.isolation == WEAK
    assert "cannot start command" in result.stderr


def test_docker_available_false_without_binary(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    assert sandbox.docker_available() is False


@pytest.mark.docker
def test_docker_reproduces_in_real_container(tmp_path):
    if not sandbox.docker_available():
        pytest.skip("docker not available")
    inspect = subprocess.run(
        ["docker", "image", "inspect", IMAGE], capture_output=True, check=False
    )
    if inspect.returncode != 0:
        pytest.skip("sandbox image not built")
    result = run_in_sandbox(tmp_path, ["python", "-c", "print('isolated')"])
    assert result.isolation == STRONG
    assert result.stdout.strip() == "isolated"

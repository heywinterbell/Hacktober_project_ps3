"""Tests for the CLI skeleton: doctor command and its availability probes."""

from __future__ import annotations

import subprocess

import httpx
from typer.testing import CliRunner

from claimcheck import cli
from claimcheck.cli import app

runner = CliRunner()


def test_doctor_runs_and_reports_both_services():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Docker:" in result.stdout
    assert "Ollama:" in result.stdout


def test_doctor_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout


def test_docker_missing_binary(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli._docker_available() is False


def test_docker_present_and_healthy(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=0, stdout=b"24.0", stderr=b"")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli._docker_available() is True


def test_docker_present_but_daemon_down(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout=b"", stderr=b"down")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli._docker_available() is False


def test_docker_timeout_counts_as_unavailable(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=5)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli._docker_available() is False


def test_docker_oserror_counts_as_unavailable(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(*args, **kwargs):
        raise OSError("cannot exec")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli._docker_available() is False


def test_ollama_reachable(monkeypatch):
    class FakeResp:
        status_code = 200

    monkeypatch.setattr(cli.httpx, "get", lambda *a, **k: FakeResp())
    assert cli._ollama_available() is True


def test_ollama_unreachable(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    assert cli._ollama_available() is False


def test_ensure_utf8_skips_streams_without_reconfigure(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdout", object())
    monkeypatch.setattr(cli.sys, "stderr", object())
    cli._ensure_utf8_stdout()  # must not raise


def test_ensure_utf8_survives_reconfigure_failure(monkeypatch):
    class BadStream:
        def reconfigure(self, **kwargs):
            raise RuntimeError("unsupported")

    monkeypatch.setattr(cli.sys, "stdout", BadStream())
    monkeypatch.setattr(cli.sys, "stderr", BadStream())
    cli._ensure_utf8_stdout()  # must not raise

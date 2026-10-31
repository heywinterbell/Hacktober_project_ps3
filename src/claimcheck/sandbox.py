"""Isolated execution for untrusted report code.

Docker is the only strong path. Without Docker we fall back to a
restricted subprocess and ALWAYS report ``isolation="weak"`` — the
caller must surface that warning; we never pretend to be isolated.

Rule: report code never runs outside :func:`run_in_sandbox`.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_IMAGE = "claimcheck-sandbox:latest"
DEFAULT_TIMEOUT = 20.0
DEFAULT_MEM = "256m"
DEFAULT_CPUS = "1"
MAX_OUTPUT_BYTES = 20 * 1024  # ~20 KB per stream
STRONG = "strong"
WEAK = "weak"

# Host variables the restricted fallback may need just to spawn a process.
# Nothing else passes through — no tokens, no app config, no HOME.
_SPAWN_KEYS = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")


@dataclass
class SandboxResult:
    """Outcome of one sandboxed run."""

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration: float
    isolation: str  # STRONG (Docker) or WEAK (restricted subprocess)
    truncated: bool = False
    command: list[str] = field(default_factory=list)

    @property
    def warning(self) -> str | None:
        """Human-visible warning that must appear in every weak report."""
        if self.isolation == WEAK:
            return "weak isolation: Docker unavailable; ran as a restricted subprocess on the host"
        return None


def docker_available() -> bool:
    """True when the Docker CLI and daemon both work."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def build_docker_command(
    root: Path,
    command: list[str],
    *,
    mem: str = DEFAULT_MEM,
    cpus: str = DEFAULT_CPUS,
    image: str = DEFAULT_IMAGE,
    container_name: str,
) -> list[str]:
    """Assemble `docker run` with every isolation flag; no env passthrough."""
    return [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "128",
        "--memory", mem,
        "--cpus", cpus,
        "--tmpfs", "/tmp:rw,size=64m",
        "--user", "1000:1000",
        "--workdir", "/workspace",
        "--volume", f"{root}:/workspace:ro",
        image,
        *command,
    ]


def _truncate(raw: bytes, limit: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    if len(raw) > limit:
        return raw[:limit].decode("utf-8", errors="replace"), True
    return raw.decode("utf-8", errors="replace"), False


def _communicate(
    proc: subprocess.Popen[bytes],
    timeout: float,
    on_timeout=None,
) -> tuple[bytes, bytes, bool]:
    """Collect output, honouring a hard timeout that kills the run."""
    try:
        out, err = proc.communicate(timeout=timeout)
        return out, err, False
    except subprocess.TimeoutExpired:
        if on_timeout is not None:
            on_timeout()
        proc.kill()
        out, err = proc.communicate()
        return out, err, True


def _run_docker(
    root: Path,
    command: list[str],
    *,
    timeout: float,
    mem: str,
    cpus: str,
    image: str,
    max_output_bytes: int,
) -> SandboxResult:
    name = f"claimcheck-{uuid.uuid4().hex[:12]}"
    argv = build_docker_command(
        root, command, mem=mem, cpus=cpus, image=image, container_name=name
    )
    started = time.monotonic()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _kill_container() -> None:
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            subprocess.run(
                ["docker", "kill", name], capture_output=True, timeout=15, check=False
            )

    out, err, timed_out = _communicate(proc, timeout, on_timeout=_kill_container)
    stdout, trunc_out = _truncate(out, max_output_bytes)
    stderr, trunc_err = _truncate(err, max_output_bytes)
    return SandboxResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=proc.returncode,
        timed_out=timed_out,
        duration=time.monotonic() - started,
        isolation=STRONG,
        truncated=trunc_out or trunc_err,
        command=argv,
    )


def _restricted_env(tmp_dir: str) -> dict[str, str]:
    """Minimal env: spawn-only keys, plus a private TMP. Nothing from the host app."""
    env = {k: os.environ[k] for k in _SPAWN_KEYS if k in os.environ}
    env["TMP"] = tmp_dir
    env["TEMP"] = tmp_dir
    return env


def _posix_limits(timeout: float):
    """Best-effort CPU/file/fd limits for the weak path (POSIX only)."""
    if os.name != "posix":
        return None
    import resource

    def _apply() -> None:
        cpu = max(1, int(timeout) + 1)
        limits = [
            (resource.RLIMIT_CPU, cpu),
            (resource.RLIMIT_FSIZE, 10 * 1024 * 1024),
            (resource.RLIMIT_NOFILE, 256),
        ]
        for which, value in limits:
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(which, (value, value))

    return _apply


def _run_weak(
    root: Path, command: list[str], *, timeout: float, max_output_bytes: int
) -> SandboxResult:
    tmp_dir = tempfile.mkdtemp(prefix="claimcheck-weak-")
    started = time.monotonic()
    try:
        try:
            proc = subprocess.Popen(
                list(command),
                cwd=root,
                env=_restricted_env(tmp_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=(os.name == "posix"),
                preexec_fn=_posix_limits(timeout),
            )
        except OSError as exc:
            return SandboxResult(
                stdout="",
                stderr=f"cannot start command: {exc}",
                exit_code=None,
                timed_out=False,
                duration=time.monotonic() - started,
                isolation=WEAK,
                command=list(command),
            )
        out, err, timed_out = _communicate(proc, timeout)
        stdout, trunc_out = _truncate(out, max_output_bytes)
        stderr, trunc_err = _truncate(err, max_output_bytes)
        stdout = stdout.rstrip("\r\n")
        stderr = stderr.rstrip("\r\n")
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode,
            timed_out=timed_out,
            duration=time.monotonic() - started,
            isolation=WEAK,
            truncated=trunc_out or trunc_err,
            command=list(command),
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_in_sandbox(
    repo_path: Path | str,
    command: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    mem: str = DEFAULT_MEM,
    cpus: str = DEFAULT_CPUS,
    image: str = DEFAULT_IMAGE,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
) -> SandboxResult:
    """Run ``command`` on the repo — Docker when possible, restricted subprocess otherwise.

    Untrusted report code must never run anywhere else. Raise
    ``max_output_bytes`` for machine-readable payloads such as coverage JSON.
    """
    root = Path(repo_path).resolve()
    if docker_available():
        return _run_docker(
            root, command,
            timeout=timeout, mem=mem, cpus=cpus, image=image,
            max_output_bytes=max_output_bytes,
        )
    return _run_weak(root, command, timeout=timeout, max_output_bytes=max_output_bytes)

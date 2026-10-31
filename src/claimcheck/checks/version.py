"""Does the claimed version exist? (git tags + pyproject metadata)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..models import Claim, Evidence, Verdict

_TAG_RE = re.compile(r"^v?(\d+\.\d+(?:\.\d+)?)$")


def _git_tags(root: Path) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "tag", "--list"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=root,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _project_version_fallback(text: str) -> str | None:
    """Read ``project.version`` without tomllib (Python 3.10 has no tomllib).

    Scoped to the single field we need: a quoted scalar assigned to ``version``
    inside the ``[project]`` table. Any ambiguity returns ``None`` so the
    caller degrades to INCONCLUSIVE rather than guessing.
    """
    in_project = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        match = re.match(r"""^version\s*=\s*["']([^"']+)["'](?:\s*#.*)?$""", line)
        if match:
            return match.group(1)
    return None


def _pyproject_version(root: Path) -> str | None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10 — tomllib is stdlib from 3.11
        return _project_version_fallback(text)
    try:
        data = tomllib.loads(text)
    except Exception:
        return None
    version = data.get("project", {}).get("version")
    return str(version) if version else None


def _normalize(ver: str) -> str:
    return ver.lstrip("v")


def check_version(root: Path, version: str) -> Evidence:
    """Confirm whether ``version`` matches a git tag or pyproject version."""
    target = _normalize(version)
    tags = _git_tags(root)
    tag_norms = {_normalize(t): t for t in tags}
    meta = _pyproject_version(root)

    if target in tag_norms:
        return Evidence(
            check="version_exists",
            verdict=Verdict.CONFIRMED,
            summary=f"✓ version {version} exists (tag {tag_norms[target]})",
            details={"version": version, "source": "git tag", "tag": tag_norms[target]},
            sandboxed=False,
        )
    if meta and _normalize(meta) == target:
        return Evidence(
            check="version_exists",
            verdict=Verdict.CONFIRMED,
            summary=f"✓ version {version} exists (pyproject.toml)",
            details={"version": version, "source": "pyproject"},
            sandboxed=False,
        )

    known = sorted(set(tag_norms) | ({_normalize(meta)} if meta else set()))
    return Evidence(
        check="version_exists",
        verdict=Verdict.REFUTED if known else Verdict.INCONCLUSIVE,
        summary=(
            f"✗ version {version} not found in tags or pyproject"
            if known
            else f"? cannot verify version {version}: no git tags or pyproject version found"
        ),
        details={"version": version, "known_versions": known},
        sandboxed=False,
    )


def check_versions(root: Path, claim: Claim) -> list[Evidence]:
    """Run the version check for every version referenced in the claim."""
    return [check_version(root, v) for v in claim.versions]

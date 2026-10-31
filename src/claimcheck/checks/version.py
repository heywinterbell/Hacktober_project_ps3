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


def _pyproject_version(root: Path) -> str | None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11 — not supported, but degrade gracefully
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
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

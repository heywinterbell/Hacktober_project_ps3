import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def sample_project() -> Path:
    """Root of the fixture repo that ClaimCheck's own tests scan."""
    return Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture
def pr_repo(tmp_path: Path) -> Path:
    """A throwaway git repo: ``main`` has ``add``; ``feature`` also adds ``sub``.

    The working tree is left on ``main`` so tests can prove the head commit,
    not the working tree, is what gets checked.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
             "-c", "commit.gpgsign=false", "-C", str(repo), *args],
            check=True,
            capture_output=True,
        )

    git("init", "-b", "main")
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "feature")
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n"
    )
    git("commit", "-am", "add sub")
    git("checkout", "main")
    return repo

from pathlib import Path

import pytest


@pytest.fixture
def sample_project() -> Path:
    """Root of the fixture repo that ClaimCheck's own tests scan."""
    return Path(__file__).parent / "fixtures" / "sample_project"

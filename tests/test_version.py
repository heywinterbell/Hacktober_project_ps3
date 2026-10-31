from pathlib import Path

from claimcheck.checks.version import (
    _project_version_fallback,
    _pyproject_version,
    check_version,
    check_versions,
)
from claimcheck.models import Claim, ReportType, Verdict


def test_version_confirmed_from_pyproject(sample_project):
    ev = check_version(sample_project, "2.4.0")
    assert ev.verdict == Verdict.CONFIRMED
    assert "pyproject" in ev.summary


def test_version_confirmed_with_v_prefix(sample_project):
    ev = check_version(sample_project, "v2.4.0")
    assert ev.verdict == Verdict.CONFIRMED


def test_version_refuted_when_unknown(sample_project):
    ev = check_version(sample_project, "9.9.9")
    assert ev.verdict == Verdict.REFUTED
    assert "2.4.0" in ev.details["known_versions"]


def test_versions_for_claim(sample_project):
    claim = Claim(type=ReportType.BUG, raw_text="x", title="x", versions=["2.4.0", "9.9.9"])
    evidence = check_versions(sample_project, claim)
    assert [e.verdict for e in evidence] == [Verdict.CONFIRMED, Verdict.REFUTED]


# --- tomllib fallback (Python 3.10 has no tomllib) ---


def test_fallback_reads_project_version():
    text = '[project]\nname = "demo"\nversion = "1.2.3"\n'
    assert _project_version_fallback(text) == "1.2.3"


def test_fallback_accepts_single_quotes():
    text = "[project]\nversion = '4.5.6'\n"
    assert _project_version_fallback(text) == "4.5.6"


def test_fallback_ignores_version_outside_project_table():
    text = '[tool.foo]\nversion = "9.9.9"\n\n[project]\nversion = "1.0.0"\n'
    assert _project_version_fallback(text) == "1.0.0"


def test_fallback_returns_none_when_absent():
    assert _project_version_fallback('[project]\nname = "demo"\n') is None


def test_fallback_returns_none_for_malformed_value():
    assert _project_version_fallback("[project]\nversion = 1.0\n") is None


def test_fallback_skips_comments_and_blank_lines():
    text = "# a comment\n\n[project]\n\nversion = \"3.2.1\"  # trailing\n"
    assert _project_version_fallback(text) == "3.2.1"


def test_pyproject_version_matches_fallback(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "7.8.9"\n', encoding="utf-8"
    )
    expected = _project_version_fallback(
        (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert _pyproject_version(tmp_path) == expected == "7.8.9"


def test_pyproject_version_none_when_missing(tmp_path: Path):
    assert _pyproject_version(tmp_path) is None

from claimcheck.checks.version import check_version, check_versions
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

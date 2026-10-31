import pytest

from claimcheck.extract import classify, extract_claim, extract_from_text, split_title_body
from claimcheck.models import ReportType


def test_split_title_body():
    title, body = split_title_body("First line\n\nRest of it")
    assert title == "First line"
    assert body == "Rest of it"


def test_split_empty():
    assert split_title_body("   ") == ("", "")


def test_classify_default_bug():
    assert classify("Crash on long URLs", "Something broke") == ReportType.BUG


def test_classify_security_keywords():
    assert classify("RCE in parse_url_v2()", "") == ReportType.SECURITY
    assert classify("Bug", "CVE-2024-1234 in parser") == ReportType.SECURITY
    assert classify("XSS vulnerability on /login", "") == ReportType.SECURITY


def test_classify_pr_keywords():
    assert classify("Fixes #120, adds tests", "Merged the change") == ReportType.PULL_REQUEST


def test_classify_kind_hint_wins():
    assert classify("Anything", "RCE exploit", kind_hint="bug") == ReportType.BUG
    assert classify("Crash", "", kind_hint="security") == ReportType.SECURITY
    assert classify("Crash", "", kind_hint="pr") == ReportType.PULL_REQUEST


def test_classify_bad_hint_raises():
    with pytest.raises(ValueError, match="unknown kind_hint"):
        classify("x", "", kind_hint="nope")


def test_extract_symbols_and_versions():
    text = "Crash in parse_url() on version 2.4.1 when given `normalize_url` input"
    claim = extract_claim(text, ReportType.BUG)
    assert "parse_url" in claim.symbols
    assert "normalize_url" in claim.symbols
    assert "2.4.1" in claim.versions
    assert claim.title == text


def test_extract_issue_refs_and_tests():
    text = "Fixes #120 and #121, adds tests for the new path"
    claim = extract_claim(text, ReportType.PULL_REQUEST)
    assert claim.issue_refs == [120, 121]
    assert claim.claims_tests is True


def test_extract_repro_snippet():
    text = "Crash on long URLs\n\n```\nparse_url('x' * 100)\n```"
    claim = extract_claim(text, ReportType.BUG)
    assert claim.repro_snippet == "parse_url('x' * 100)"


def test_extract_no_repro_snippet():
    claim = extract_claim("Just a title", ReportType.BUG)
    assert claim.repro_snippet is None
    assert claim.claims_tests is False


def test_extract_from_text_end_to_end():
    claim = extract_from_text("RCE in `parse_url_v2()` — versions 2.4.1")
    assert claim.type == ReportType.SECURITY
    assert "parse_url_v2" in claim.symbols
    assert "2.4.1" in claim.versions

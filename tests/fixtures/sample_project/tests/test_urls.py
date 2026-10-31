"""Tests for the sample_fixture package (the project under test)."""

from sample_fixture.urls import _long_url_crash, normalize_url, parse_url


def test_parse_url_basic():
    result = parse_url("https://example.com/path")
    assert result["scheme"] == "https"
    assert result["host"] == "example.com"
    assert result["path"] == "/path"


def test_normalize_url():
    assert normalize_url("HTTPS://Example.COM/Path/") == "https://example.com/Path"


def test_long_url_crash_short_ok():
    assert _long_url_crash("x" * 10) == "x"

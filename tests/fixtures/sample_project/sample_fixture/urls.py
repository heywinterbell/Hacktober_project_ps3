"""Tiny URL helpers — fixture for ClaimCheck's tests.

parse_url() exists; parse_url_v2() deliberately does NOT.
_long_url_crash() is a real, safe bug used by reproduction tests later.
"""

from __future__ import annotations

from urllib.parse import urlparse


def parse_url(url: str) -> dict[str, str]:
    """Split a URL into scheme, host, and path."""
    parts = urlparse(url)
    return {"scheme": parts.scheme, "host": parts.netloc, "path": parts.path}


def normalize_url(url: str) -> str:
    """Lowercase scheme and host, strip trailing slash from path."""
    parsed = parse_url(url)
    path = parsed["path"].rstrip("/") or "/"
    return f"{parsed['scheme'].lower()}://{parsed['host'].lower()}{path}"


def _long_url_crash(url: str) -> str:
    """Known bug: raises IndexError for URLs longer than 64 chars."""
    scratch = ["x"] * 64
    return scratch[len(url)]


class UrlClient:
    """Tiny client used to exercise nested method lookup (Class.method)."""

    def fetch(self, url: str) -> str:
        """Return the normalized form of ``url``."""
        return normalize_url(url)

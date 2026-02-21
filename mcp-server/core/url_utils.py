"""
URL and domain utilities for source ranking.
"""
import re
from typing import Final
from urllib.parse import urlparse


SOCIAL_HOST_MARKERS: Final[tuple] = (
    "reddit.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "pinterest.com",
    "linkedin.com",
    "quora.com",
)

REFERENCE_HOST_MARKERS: Final[tuple] = (
    "wikipedia.org",
    "britannica.com",
    "nationalgeographic.com",
    "smithsonianmag.com",
    "who.int",
    "cdc.gov",
    "nih.gov",
    "nasa.gov",
    "noaa.gov",
    "extension.",
)

DOCUMENTATION_HOST_MARKERS: Final[tuple] = (
    "docs.",
    "developer.",
    "readthedocs",
    "mdn",
)


def normalize_url(url: str) -> str:
    """Normalize URL for deduplication."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower() if parsed.scheme else "https"
        netloc = parsed.netloc.lower().lstrip("www.")
        path = parsed.path.rstrip("/")
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return url.lower().strip()


def domain_trust_score(url: str) -> float:
    """Calculate trust score based on domain."""
    if not url:
        return 0.4
    host = urlparse(url).netloc.lower()
    if not host:
        return 0.4

    if any(marker in host for marker in REFERENCE_HOST_MARKERS):
        return 0.92
    if host.endswith(".gov") or host.endswith(".edu"):
        return 0.88
    if any(marker in host for marker in ("wikipedia.org",)):
        return 0.85
    if any(marker in host for marker in ("github.com", "gitlab.com", "sourceforge.net")):
        return 0.82
    if any(marker in host for marker in ("stackoverflow.com", " Stack Overflow".strip())):
        return 0.78
    if any(marker in host for marker in SOCIAL_HOST_MARKERS):
        return 0.35
    if host.endswith(".org"):
        return 0.62
    if host.endswith(".com"):
        return 0.55
    if host.endswith(".net"):
        return 0.5
    if host.endswith(".io"):
        return 0.58
    return 0.45


def host_category(host: str) -> str:
    """Categorize host type."""
    host = (host or "").lower()
    if any(marker in host for marker in SOCIAL_HOST_MARKERS):
        return "social"
    if any(marker in host for marker in DOCUMENTATION_HOST_MARKERS):
        return "docs"
    if host.endswith(".edu") or host.endswith(".gov") or any(marker in host for marker in REFERENCE_HOST_MARKERS):
        return "reference"
    if any(marker in host for marker in ("youtube.com", "youtu.be", "vimeo.com")):
        return "video"
    if any(marker in host for marker in ("news", "times", "post", "reuters", "apnews", "bbc")):
        return "news"
    return "other"

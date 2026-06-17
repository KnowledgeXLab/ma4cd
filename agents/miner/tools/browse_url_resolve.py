"""
Browse URL normalization and DTIC/DSIAC resilience helpers.
"""
from __future__ import annotations

import re
from typing import List, Tuple
from urllib.parse import urlparse, urlunparse

# Hosts that no longer resolve or have moved (netloc without port, lowercase).
_HOST_ALIASES = {
    "dsiac.dtic.mil": "www.dsiac.org",
}

_DTIC_HOSTS = frozenset(
    {
        "apps.dtic.mil",
        "discover.dtic.mil",
        "www.dtic.mil",
        "dtic.mil",
    }
)

_CITATION_RE = re.compile(r"/sti/citations/([A-Za-z0-9]+)", re.I)
_STI_HTML_TR_RE = re.compile(r"/sti/html/tr/([A-Za-z0-9]+)", re.I)

# Homepage fallback is slow and rarely helps; cap how many discover URLs we try.
_MAX_DTIC_FALLBACKS = 2


def normalize_browse_url(url: str) -> Tuple[str, bool]:
    """
    Rewrite known-dead hostnames before Playwright navigation.
    Returns (resolved_url, was_remapped).
    """
    if not url or not url.startswith("http"):
        return url, False

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host_key = host[4:]
    else:
        host_key = host

    alias = _HOST_ALIASES.get(host_key)
    if not alias:
        return url, False

    remapped = parsed._replace(netloc=alias)
    return urlunparse(remapped), True


def is_dtic_host(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host.endswith("dtic.mil") or host in _DTIC_HOSTS


def dtic_403_fallback_urls(url: str) -> List[str]:
    """
    When apps.dtic.mil returns 403, try public Discover portal equivalents.
    """
    if not is_dtic_host(url):
        return []

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    fallbacks: List[str] = []

    if host in ("apps.dtic.mil", "www.apps.dtic.mil"):
        for pattern in (_CITATION_RE, _STI_HTML_TR_RE):
            match = pattern.search(parsed.path or "")
            if match:
                accession = match.group(1)
                fallbacks.append(f"https://discover.dtic.mil/results?q={accession}")
                break

        path = (parsed.path or "").strip("/")
        if path and path not in ("sti", "sti/citations") and not fallbacks:
            fallbacks.append(f"https://discover.dtic.mil/results?q={path.replace('/', ' ')}")

    # Do not queue discover.dtic.mil/ — it often hangs headless browsers with little payoff.
    # Deduplicate while preserving order
    seen = set()
    unique: List[str] = []
    for item in fallbacks:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:_MAX_DTIC_FALLBACKS]


def is_noise_browse_url(url: str) -> bool:
    """Skip known exploit probes / editor shells that stall Playwright."""
    if not url:
        return True
    lower = url.lower()
    noise_tokens = (
        "/fckeditor/editor/filemanager",
        "/ckeditor/filemanager",
        "connector=%2f%5c%2f",
        "getfoldersandfiles=",
    )
    return any(token in lower for token in noise_tokens)


def should_attempt_dtic_fallback(browse_result: dict) -> bool:
    if not browse_result or browse_result.get("success"):
        return False

    err = str(browse_result.get("error", "")).lower()
    status = browse_result.get("status")
    if status in (403, 401, 429):
        return True
    return any(
        token in err
        for token in (
            "403",
            "401",
            "429",
            "forbidden",
            "access denied",
            "http_soft_error_403",
            "http_soft_error_401",
        )
    )


def merge_access_denied_signal(browse_result: dict) -> bool:
    """True if response looks blocked by WAF / auth (used by ExtractNode)."""
    if not browse_result:
        return False
    if browse_result.get("access_denied"):
        return True

    err = str(browse_result.get("error", "")).lower()
    html = str(browse_result.get("html", "")).lower()
    status = browse_result.get("status")

    if status in (403, 401):
        return True
    if any(x in err for x in ("403", "401", "forbidden", "access denied", "http_soft_error_403")):
        return True
    return any(
        x in html
        for x in (
            "captcha",
            "access denied",
            "security check",
            "cloudflare",
            "verify you are human",
        )
    )

"""
Shared primp browser profile selector.

primp (the TLS-impersonation library used by curl-cffi and independently)
ships with a fixed set of browser profiles per version. Profiles get retired
as the underlying browser versions age out. Hardcoding a specific profile
(e.g. "chrome_120") breaks silently when primp upgrades — primp falls back
to "random" and the JA3 fingerprint is no longer Chrome-shaped, defeating
the purpose of impersonation.

This helper probes a list of candidate profiles at import time and picks
the newest one that primp accepts without a warning. The result is cached
for the process lifetime.

Note: primp uses underscores (chrome_120, firefox_123) while curl-cffi
uses no underscores (chrome120, firefox120). This module exposes both
forms via get_chrome_profile() (primp form) and get_chrome_profile_curl()
(curl-cffi form).
"""
from __future__ import annotations

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Candidate profiles, newest first. We prefer Chrome (most common), then
# Firefox, then Safari as fallbacks. The list is intentionally long so that
# as primp/curl-cffi add newer profiles (chrome_136, chrome_140, ...) this
# code picks them up without requiring a code change.
_CHROME_CANDIDATES_PRIMP = [
    "chrome_140", "chrome_136", "chrome_135", "chrome_133",
    "chrome_131", "chrome_124", "chrome_120",
]
_FIREFOX_CANDIDATES_PRIMP = [
    "firefox_135", "firefox_133", "firefox_128", "firefox_123",
]
_SAFARI_CANDIDATES_PRIMP = [
    "safari_17_5", "safari_17_0", "safari_16_5",
]

# curl-cffi uses no underscore: chrome120, firefox120, safari17_0
_CHROME_CANDIDATES_CURL = [c.replace("_", "") for c in _CHROME_CANDIDATES_PRIMP]
_FIREFOX_CANDIDATES_CURL = [c.replace("_", "") for c in _FIREFOX_CANDIDATES_PRIMP]

_cached_chrome: Optional[str] = None
_cached_firefox: Optional[str] = None
_cached_chrome_curl: Optional[str] = None
_cached_any: Optional[str] = None


def _probe_primp(profile: str) -> bool:
    """Return True if primp accepts `profile` without the 'does not exist' warning."""
    try:
        import primp
    except ImportError:
        return False

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    primp_logger = logging.getLogger("primp.impersonate")
    primp_logger.addHandler(handler)
    try:
        primp.Client(impersonate=profile)
        warning = buf.getvalue()
        return "does not exist" not in warning
    except Exception:
        return False
    finally:
        primp_logger.removeHandler(handler)


def _probe_curl_cffi(profile: str) -> bool:
    """Return True if curl_cffi accepts `profile` without raising ImpersonateError."""
    try:
        import curl_cffi.requests
    except ImportError:
        return False
    try:
        # We don't actually make a request — just construct the impersonate
        # config. The cheapest way to test is a HEAD to httpbin with a short
        # timeout; if the profile is invalid it raises ImpersonateError
        # synchronously before any network I/O.
        curl_cffi.requests.head(
            "https://httpbin.org/head",
            impersonate=profile,
            timeout=2,
        )
        return True
    except Exception as e:
        # ImpersonateError means the profile is not supported; network errors
        # mean the profile IS supported (we just couldn't reach httpbin).
        return "Impersonat" not in type(e).__name__


def get_chrome_profile() -> str:
    """Return the newest valid Chrome profile name for primp. Falls back to 'chrome_124'."""
    global _cached_chrome
    if _cached_chrome is not None:
        return _cached_chrome
    for candidate in _CHROME_CANDIDATES_PRIMP:
        if _probe_primp(candidate):
            _cached_chrome = candidate
            logger.debug("Selected primp Chrome profile: %s", candidate)
            return candidate
    _cached_chrome = "chrome_124"
    return _cached_chrome


def get_firefox_profile() -> str:
    """Return the newest valid Firefox profile name for primp. Falls back to 'firefox_123'."""
    global _cached_firefox
    if _cached_firefox is not None:
        return _cached_firefox
    for candidate in _FIREFOX_CANDIDATES_PRIMP:
        if _probe_primp(candidate):
            _cached_firefox = candidate
            logger.debug("Selected primp Firefox profile: %s", candidate)
            return candidate
    _cached_firefox = "firefox_123"
    return _cached_firefox


def get_chrome_profile_curl() -> str:
    """Return the newest valid Chrome profile name for curl-cffi (no underscore). Falls back to 'chrome124'."""
    global _cached_chrome_curl
    if _cached_chrome_curl is not None:
        return _cached_chrome_curl
    for candidate in _CHROME_CANDIDATES_CURL:
        if _probe_curl_cffi(candidate):
            _cached_chrome_curl = candidate
            logger.debug("Selected curl-cffi Chrome profile: %s", candidate)
            return candidate
    _cached_chrome_curl = "chrome124"
    return _cached_chrome_curl


def get_any_profile() -> str:
    """Return the newest valid profile across all browsers (primp form). Prefers Chrome."""
    global _cached_any
    if _cached_any is not None:
        return _cached_any
    for candidate in _CHROME_CANDIDATES_PRIMP + _FIREFOX_CANDIDATES_PRIMP + _SAFARI_CANDIDATES_PRIMP:
        if _probe_primp(candidate):
            _cached_any = candidate
            return candidate
    _cached_any = "chrome_124"
    return _cached_any


import threading

GLOBAL_PRIMP_LOCK = threading.Lock()


def safe_primp_get(url: str, impersonate: Optional[str] = None, timeout: float = 15.0, follow_redirects: bool = True):
    """
    Thread-safe wrapper around primp.Client().get() to prevent C-extension race conditions across threads.
    """
    try:
        import primp
        profile = impersonate or get_chrome_profile()
        with GLOBAL_PRIMP_LOCK:
            c = primp.Client(impersonate=profile, follow_redirects=follow_redirects)
            return c.get(url, timeout=timeout)
    except Exception as e:
        logger.debug(f"safe_primp_get failed for {url}: {e}")
        return None


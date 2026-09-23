from __future__ import annotations

from tools.web import _validate_url


class WebFetchAuthorizationAdapter:
    """Authorization via the real SSRF guard.

    `_validate_url` is the single source of truth for URL policy
    (scheme, DNS resolution, private/loopback/link-local rejection,
    per-hop re-validation). The runner re-validates anyway, so this
    is deny-before-runner, not a replacement.
    """

    def can_fetch(self, url: str) -> bool:
        if not isinstance(url, str) or not url.strip():
            return False
        valid, _reason = _validate_url(url.strip())
        return valid

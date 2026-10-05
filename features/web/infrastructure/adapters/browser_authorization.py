from __future__ import annotations

from urllib.parse import urlparse
import ipaddress


class BrowserAuthorizationAdapter:
    """SSRF guard: only public http(s) URLs, no private IPs."""

    def can_browse(self, url: str) -> bool:
        try:
            parsed = urlparse(url.strip())
            if parsed.scheme not in ("http", "https"):
                return False
            host = parsed.hostname or ""
            if not host:
                return False
            # Block private IPs
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return False
            except ValueError:
                pass  # hostname, not IP — allow
            # Block localhost variants
            if host.lower() in ("localhost", "127.0.0.1", "::1"):
                return False
            return True
        except Exception:
            return False

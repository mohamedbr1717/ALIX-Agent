from __future__ import annotations

from abc import ABC, abstractmethod


class BrowserAuthorizationPort(ABC):
    @abstractmethod
    def can_browse(self, url: str) -> bool:
        """SSRF guard: allow only public http(s) URLs."""

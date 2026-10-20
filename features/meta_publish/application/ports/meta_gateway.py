"""Port for the Meta Graph API gateway (implemented in infrastructure)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class MetaGateway(ABC):
    @abstractmethod
    def post_text(self, message: str, link: str = "") -> dict:
        """Publish a text/link post to the Page. Result dict with 'ok'."""

    @abstractmethod
    def post_photo(self, image_path: str, caption: str = "") -> dict:
        """Publish a workspace image to the Page. Result dict with 'ok'."""

"""Controllers for the Meta publishing feature (Facebook, phase 1)."""
from __future__ import annotations

from typing import Any

from features.meta_publish.application.dto.meta_publish import (
    PostPhotoRequest,
    PostTextRequest,
)


class FacebookPostTextController:
    """Builds a PostTextRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = PostTextRequest(
            message=str(arguments.get("message", "")),
            link=str(arguments.get("link", "") or ""),
        )
        return self._use_case.execute(request)


class FacebookPostPhotoController:
    """Builds a PostPhotoRequest from external arguments."""

    def __init__(self, use_case: Any) -> None:
        self._use_case = use_case

    def handle(self, arguments: dict) -> dict:
        request = PostPhotoRequest(
            image_path=str(arguments.get("image_path", "")).strip(),
            caption=str(arguments.get("caption", "") or ""),
        )
        return self._use_case.execute(request)

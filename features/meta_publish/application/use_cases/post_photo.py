"""Publish a Facebook photo post; authorization is checked before the gateway."""
from __future__ import annotations

from typing import Any

from features.meta_publish.application.dto.meta_publish import PostPhotoRequest

TOOL_NAME = "facebook_post_photo"


class PostPhotoUseCase:
    def __init__(self, authorization: Any, gateway: Any) -> None:
        self._authorization = authorization
        self._gateway = gateway

    def execute(self, request: PostPhotoRequest) -> dict:
        if not self._authorization.can_publish():
            return {
                "ok": False,
                "action": TOOL_NAME,
                "message": "مرفوضة بواسطة السياسة.",
                "evidence": {},
            }
        return self._gateway.post_photo(request.image_path, request.caption)

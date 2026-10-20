"""DTOs for the Meta publishing feature (Facebook Page, phase 1)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PostTextRequest:
    message: str
    link: str = ""


@dataclass(frozen=True)
class PostPhotoRequest:
    image_path: str
    caption: str = ""

"""Composition root for the Meta publishing feature (Facebook, phase 1)."""
from __future__ import annotations

from typing import Any

from features.meta_publish.application.use_cases.post_photo import (
    PostPhotoUseCase,
)
from features.meta_publish.application.use_cases.post_text import (
    PostTextUseCase,
)
from features.meta_publish.infrastructure.adapters.graph_api_gateway import (
    GraphApiGateway,
)
from features.meta_publish.infrastructure.adapters.policy_meta_authorization import (
    PolicyMetaAuthorizationAdapter,
)
from features.meta_publish.interfaces.controllers.facebook_controllers import (
    FacebookPostPhotoController,
    FacebookPostTextController,
)


def build_facebook_post_text_controller(policy: Any) -> FacebookPostTextController:
    """Build the facebook_post_text controller."""
    authorization = PolicyMetaAuthorizationAdapter(policy, "facebook_post_text")
    gateway = GraphApiGateway()
    use_case = PostTextUseCase(authorization=authorization, gateway=gateway)
    return FacebookPostTextController(use_case)


def build_facebook_post_photo_controller(policy: Any) -> FacebookPostPhotoController:
    """Build the facebook_post_photo controller."""
    authorization = PolicyMetaAuthorizationAdapter(policy, "facebook_post_photo")
    gateway = GraphApiGateway()
    use_case = PostPhotoUseCase(authorization=authorization, gateway=gateway)
    return FacebookPostPhotoController(use_case)

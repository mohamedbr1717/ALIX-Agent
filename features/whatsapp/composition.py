"""Composition root for the WhatsApp feature (Cloud API)."""
from __future__ import annotations

from typing import Any

from features.whatsapp.application.use_cases.send_message import (
    SendWhatsAppUseCase,
)
from features.whatsapp.infrastructure.adapters.cloud_api_gateway import (
    CloudApiGateway,
)
from features.whatsapp.infrastructure.adapters.policy_whatsapp_authorization import (
    PolicyWhatsAppAuthorizationAdapter,
)
from features.whatsapp.interfaces.controllers.whatsapp_controller import (
    SendWhatsAppController,
)


def build_whatsapp_send_controller(policy: Any) -> SendWhatsAppController:
    """Build the whatsapp_send controller."""
    authorization = PolicyWhatsAppAuthorizationAdapter(policy)
    gateway = CloudApiGateway()
    use_case = SendWhatsAppUseCase(
        authorization=authorization, gateway=gateway
    )
    return SendWhatsAppController(use_case)

"""Composition root for the phone feature (Termux:API bridge)."""
from __future__ import annotations

from typing import Any

from features.phone.application.use_cases.notify import NotifyUseCase
from features.phone.application.use_cases.phone_call import PhoneCallUseCase
from features.phone.application.use_cases.send_sms import SendSmsUseCase
from features.phone.infrastructure.adapters.policy_phone_authorization import (
    PolicyPhoneAuthorizationAdapter,
)
from features.phone.infrastructure.adapters.termux_api_gateway import (
    TermuxApiGateway,
)
from features.phone.interfaces.controllers.phone_controller import (
    NotifyController,
    PhoneCallController,
    SendSmsController,
)


def _parts(policy: Any):
    authorization = PolicyPhoneAuthorizationAdapter(policy)
    gateway = TermuxApiGateway()
    return authorization, gateway


def build_phone_call_controller(policy: Any) -> PhoneCallController:
    """Build the phone_call controller."""
    authorization, gateway = _parts(policy)
    use_case = PhoneCallUseCase(authorization=authorization, gateway=gateway)
    return PhoneCallController(use_case)


def build_send_sms_controller(policy: Any) -> SendSmsController:
    """Build the send_sms controller."""
    authorization, gateway = _parts(policy)
    use_case = SendSmsUseCase(authorization=authorization, gateway=gateway)
    return SendSmsController(use_case)


def build_notify_controller(policy: Any) -> NotifyController:
    """Build the notify controller."""
    authorization, gateway = _parts(policy)
    use_case = NotifyUseCase(authorization=authorization, gateway=gateway)
    return NotifyController(use_case)

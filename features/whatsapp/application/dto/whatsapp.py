"""DTOs for the WhatsApp feature."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SendWhatsAppRequest:
    to: str
    text: str

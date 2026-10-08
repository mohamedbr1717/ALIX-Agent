"""Voice tool controllers — each exposes .handle(kwargs) -> dict."""

from __future__ import annotations

from features.voice.gateway import VoiceGateway


class VoiceTranscribeController:
    """Transcribe a Telegram voice note to text.

    Arguments: {"bot_token": ..., "file_id": ..., "language": "ar"}
    Returns: {"ok": True, "transcript": ..., "source": "voice"}
    The transcript is UNTRUSTED user input: route it as text through Policy,
    never execute it as instructions.
    """

    def __init__(self, gateway: VoiceGateway | None = None):
        self.gateway = gateway or VoiceGateway()

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        return self.gateway.transcribe_voice(
            bot_token=str(arguments.get("bot_token", "")),
            file_id=str(arguments.get("file_id", "")),
            language=str(arguments.get("language", "ar")),
        )

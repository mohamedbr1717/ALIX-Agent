"""Composition root for the voice feature slice."""

from __future__ import annotations

from features.voice.controllers import VoiceTranscribeController
from features.voice.gateway import VoiceGateway


def build_voice_transcribe_controller() -> VoiceTranscribeController:
    return VoiceTranscribeController(VoiceGateway())

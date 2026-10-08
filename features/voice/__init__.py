"""Voice feature slice: Telegram voice messages -> Groq Whisper -> text.

Phase 1 of ALIX الصوتي: voice is just an alternative keyboard.
The transcript is injected as plain text into the existing agent pipeline.
Transcripts are UNTRUSTED input (like email bodies): never executed as
instructions, only routed as user text through Policy.
"""

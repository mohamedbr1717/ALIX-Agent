"""Composition root for the gmail feature slice."""

from __future__ import annotations

from features.gmail.controllers import (
    GmailReadController,
    GmailReplyController,
    GmailSearchController,
    GmailSendController,
)
from features.gmail.gateway import GmailGateway


def build_gmail_search_controller() -> GmailSearchController:
    return GmailSearchController(GmailGateway())


def build_gmail_read_controller() -> GmailReadController:
    return GmailReadController(GmailGateway())


def build_gmail_reply_controller() -> GmailReplyController:
    return GmailReplyController(GmailGateway())


def build_gmail_send_controller() -> GmailSendController:
    return GmailSendController(GmailGateway())

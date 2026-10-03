"""Gmail tool controllers — each exposes .handle(kwargs) -> dict."""

from __future__ import annotations

from features.gmail.gateway import GmailGateway


class GmailSearchController:
    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        return self.gateway.search(
            query=arguments.get("query", ""),
            limit=arguments.get("max_results", 10),
        )


class GmailReadController:
    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        message_id = arguments.get("message_id", "")
        if not message_id:
            return {"ok": False, "error": "message_id مطلوب."}
        return self.gateway.read(str(message_id))


class GmailReplyController:
    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        message_id = str(arguments.get("message_id", ""))
        body = arguments.get("body", "")
        if not message_id:
            return {"ok": False, "error": "message_id مطلوب."}
        if not (body or "").strip():
            return {"ok": False, "error": "نص الرد فارغ."}
        original = self.gateway.read(message_id)
        if not original.get("ok"):
            return original
        subject = original.get("subject") or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}" if subject else "Re:"
        to = original.get("from", "")
        # Extract bare address from "Name <addr>" if present.
        import re

        m = re.search(r"<([^>]+)>", to)
        if m:
            to = m.group(1)
        return self.gateway.send(
            to=to.strip(),
            subject=subject,
            body=body,
            in_reply_to=original.get("uid", ""),
        )


class GmailSendController:
    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        arguments = arguments or {}
        return self.gateway.send(
            to=arguments.get("to", ""),
            subject=arguments.get("subject", ""),
            body=arguments.get("body", ""),
        )

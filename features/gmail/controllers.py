"""Gmail tool controllers — each exposes .handle(kwargs) -> dict."""

from __future__ import annotations

from features.gmail.gateway import GmailGateway


class GmailSearchController:
    """Search across all configured Gmail accounts (multi-account).

    Each result is labeled with 'account'. Optional 'account' argument
    targets one account (1/2 or address).
    """

    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        from features.gmail.gateway import (
            GmailGateway as _GW,
            get_configured_accounts,
            _resolve_account,
        )
        arguments = arguments or {}
        query = arguments.get("query", "")
        limit = arguments.get("max_results", 10)
        account_arg = arguments.get("account")

        accounts = get_configured_accounts()
        if not accounts:
            # Fall back to single-gateway behavior (will return config error)
            return self.gateway.search(query=query, limit=limit)

        # Target one account?
        if account_arg is not None:
            resolved = _resolve_account(account_arg)
            if not resolved:
                return {"ok": False, "error": f"الحساب غير موجود: {account_arg}"}
            gw = _GW(address=resolved[0], app_password=resolved[1])
            result = gw.search(query=query, limit=limit)
            if result.get("ok"):
                for m in result.get("messages", []):
                    m["account"] = resolved[0]
            return result

        # Search all accounts, merge and label
        all_messages = []
        errors = []
        per_account = max(1, int(limit) // len(accounts)) if accounts else int(limit)
        for addr, pwd in accounts:
            gw = _GW(address=addr, app_password=pwd)
            r = gw.search(query=query, limit=per_account)
            if r.get("ok"):
                for m in r.get("messages", []):
                    m["account"] = addr
                    all_messages.append(m)
            else:
                errors.append(f"{addr}: {r.get('error', '?')}")
        # Sort by date descending if parseable, else keep account order
        return {
            "ok": True,
            "messages": all_messages[: int(limit)],
            "count": len(all_messages[: int(limit)]),
            "accounts_searched": [a for a, _ in accounts],
            "errors": errors,
        }


class GmailReadController:
    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        from features.gmail.gateway import (
            GmailGateway as _GW,
            get_configured_accounts,
            _resolve_account,
        )
        arguments = arguments or {}
        message_id = arguments.get("message_id", "")
        if not message_id:
            return {"ok": False, "error": "message_id مطلوب."}
        account_arg = arguments.get("account")
        if account_arg is not None:
            resolved = _resolve_account(account_arg)
            if not resolved:
                return {"ok": False, "error": f"الحساب غير موجود: {account_arg}"}
            gw = _GW(address=resolved[0], app_password=resolved[1])
            result = gw.read(str(message_id))
            if result.get("ok"):
                result["account"] = resolved[0]
            return result
        # Try each account until the message is found
        accounts = get_configured_accounts()
        if not accounts:
            return self.gateway.read(str(message_id))
        last_error = None
        for addr, pwd in accounts:
            gw = _GW(address=addr, app_password=pwd)
            r = gw.read(str(message_id))
            if r.get("ok"):
                r["account"] = addr
                return r
            last_error = r
        return last_error or {"ok": False, "error": "الرسالة غير موجودة."}


class GmailReplyController:
    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        from features.gmail.gateway import (
            GmailGateway as _GW,
            get_configured_accounts,
            _resolve_account,
        )
        arguments = arguments or {}
        message_id = str(arguments.get("message_id", ""))
        body = arguments.get("body", "")
        account_arg = arguments.get("account")
        if not message_id:
            return {"ok": False, "error": "message_id مطلوب."}
        if not (body or "").strip():
            return {"ok": False, "error": "نص الرد فارغ."}
        # Resolve which account to read from and send from
        send_gateway = self.gateway
        reply_account = None
        if account_arg is not None:
            resolved = _resolve_account(account_arg)
            if not resolved:
                return {"ok": False, "error": f"الحساب غير موجود: {account_arg}"}
            send_gateway = _GW(address=resolved[0], app_password=resolved[1])
            reply_account = resolved[0]
            original = send_gateway.read(message_id)
        else:
            # Find the message across accounts; reply from where it was found
            accounts = get_configured_accounts()
            original = None
            if accounts:
                for addr, pwd in accounts:
                    gw = _GW(address=addr, app_password=pwd)
                    r = gw.read(message_id)
                    if r.get("ok"):
                        original = r
                        send_gateway = gw
                        reply_account = addr
                        break
            if original is None:
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
        result = send_gateway.send(
            to=to.strip(),
            subject=subject,
            body=body,
            in_reply_to=original.get("uid", ""),
        )
        if result.get("ok") and reply_account:
            result["account"] = reply_account
        return result


class GmailSendController:
    def __init__(self, gateway: GmailGateway | None = None):
        self.gateway = gateway or GmailGateway()

    def handle(self, arguments: dict) -> dict:
        from features.gmail.gateway import (
            GmailGateway as _GW,
            _resolve_account,
        )
        arguments = arguments or {}
        account_arg = arguments.get("account")
        gateway = self.gateway
        used_account = None
        if account_arg is not None:
            resolved = _resolve_account(account_arg)
            if not resolved:
                return {"ok": False, "error": f"الحساب غير موجود: {account_arg}"}
            gateway = _GW(address=resolved[0], app_password=resolved[1])
            used_account = resolved[0]
        result = gateway.send(
            to=arguments.get("to", ""),
            subject=arguments.get("subject", ""),
            body=arguments.get("body", ""),
        )
        if result.get("ok") and used_account:
            result["account"] = used_account
        return result

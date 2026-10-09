"""Compute inverse operations for reversible tools."""

from __future__ import annotations


def compute_inverse(
    tool_name: str, arguments: dict, result: dict
) -> dict | None:
    """Return {"tool": ..., "arguments": ...} to undo, or None.

    Only successful executions with sufficient result data qualify.
    Secrets are never included (arguments are pre-redacted by policy).
    """
    if not result.get("ok"):
        return None

    if tool_name == "calendar_add":
        event_id = result.get("event_id")
        if event_id:
            return {
                "tool": "calendar_delete",
                "arguments": {"event_id": event_id},
            }

    return None


def summarize_action(
    tool_name: str, arguments: dict, result: dict
) -> str:
    """Short Arabic summary for history display."""
    if tool_name == "calendar_add":
        return f"أضاف موعدًا: {arguments.get('title', '')}"
    if tool_name == "calendar_delete":
        return "حذف موعدًا"
    if tool_name == "calendar_list":
        return "عرض المواعيد"
    if tool_name == "resolve_contact":
        return f"حل جهة اتصال: {arguments.get('name', '')}"
    if tool_name == "phone_call":
        return f"مكالمة: {arguments.get('number', '')}"
    if tool_name == "send_sms":
        return f"رسالة نصية: {arguments.get('number', '')}"
    return f"نفذ {tool_name}"

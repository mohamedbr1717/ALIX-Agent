from __future__ import annotations

from typing import Any

from features.contacts.application.dto.resolve_contact import (
    ResolveContactRequest,
)
from features.contacts.domain.contact import normalize_arabic_name


class ResolveContactUseCase:
    """Resolve a contact name to a phone number.

    Read-only. Fail-closed:
    - empty query → rejected
    - no match → not found (no guessing)
    - multiple matches → candidates listed, no auto-pick
    - repository error → empty result, never an exception
    """

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def execute(self, request: ResolveContactRequest) -> dict:
        query = normalize_arabic_name(request.name or "")
        if not query:
            return {
                "ok": False,
                "action": "resolve_contact",
                "message": "اسم جهة فارغ.",
                "evidence": {},
            }

        try:
            contacts = self._repository.all()
        except Exception:
            contacts = []

        if not contacts:
            return {
                "ok": False,
                "action": "resolve_contact",
                "message": "دفتر الجهات غير متاح حاليًا.",
                "evidence": {},
            }

        # 1. Exact normalized match
        exact = [c for c in contacts if c.normalized_name == query]
        if len(exact) == 1:
            return self._found(exact[0])
        if len(exact) > 1:
            return self._ambiguous(exact)

        # 2. Substring match on normalized names
        partial = [c for c in contacts if query in c.normalized_name]
        if len(partial) == 1:
            return self._found(partial[0])
        if len(partial) > 1:
            return self._ambiguous(partial)

        return {
            "ok": False,
            "action": "resolve_contact",
            "message": f"لا توجد جهة باسم '{request.name}'.",
            "evidence": {"query": request.name},
        }

    @staticmethod
    def _found(contact: Any) -> dict:
        return {
            "ok": True,
            "action": "resolve_contact",
            "message": f"تم العثور على {contact.name}.",
            "number": contact.number,
            "evidence": {"name": contact.name},
        }

    @staticmethod
    def _ambiguous(contacts: list) -> dict:
        names = [c.name for c in contacts[:10]]
        return {
            "ok": False,
            "action": "resolve_contact",
            "message": (
                "عدة جهات تطابق الاسم — حدد المقصود: "
                + "، ".join(names)
            ),
            "evidence": {"candidates": names},
        }

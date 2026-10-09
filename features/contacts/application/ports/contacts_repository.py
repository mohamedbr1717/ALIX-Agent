"""Port for contact storage."""

from __future__ import annotations

from typing import Protocol

from features.contacts.domain.contact import Contact


class ContactsRepository(Protocol):
    """Read-only access to the phone book."""

    def all(self) -> list[Contact]:
        """Return all contacts. Fail-closed: empty list on any error."""
        ...

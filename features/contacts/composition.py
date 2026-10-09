"""Composition root for the contacts feature slice."""

from __future__ import annotations

from typing import Any

from features.contacts.application.use_cases.resolve_contact import (
    ResolveContactUseCase,
)
from features.contacts.infrastructure.adapters.json_contacts_repository import (
    JsonContactsRepository,
)
from features.contacts.interfaces.controllers.contacts_controller import (
    ResolveContactController,
)


def build_resolve_contact_controller(
    policy: Any,
    contacts_path: Any | None = None,
) -> ResolveContactController:
    """Build the resolve_contact controller (read-only tool)."""
    repository = JsonContactsRepository(path=contacts_path)
    use_case = ResolveContactUseCase(repository=repository)
    return ResolveContactController(use_case)

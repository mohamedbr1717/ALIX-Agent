"""JSON-file contacts repository (phone_queue/contacts.json)."""

from __future__ import annotations

import json
from pathlib import Path

from features.contacts.domain.contact import Contact


class JsonContactsRepository:
    """Read contacts from the synced JSON file.

    Fail-closed: missing file, bad JSON, or bad entries → empty list.
    Results are cached and refreshed when the file mtime changes.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(
            path
            or Path.home() / "ALIX-Agent" / "phone_queue" / "contacts.json"
        )
        self._cache: list[Contact] | None = None
        self._mtime: float | None = None

    def all(self) -> list[Contact]:
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return []
        if self._cache is not None and self._mtime == mtime:
            return self._cache
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        contacts: list[Contact] = []
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name", "") or "").strip()
                number = str(entry.get("number", "") or "").strip()
                if name and number:
                    contacts.append(Contact(name=name, number=number))
        self._cache = contacts
        self._mtime = mtime
        return contacts

"""Contact domain entity and Arabic name normalization."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalize_arabic_name(name: str) -> str:
    """Normalize an Arabic name for matching.

    - strips diacritics (tashkeel)
    - أ/إ/آ → ا, ؤ → و, ئ → ي
    - ة → ه (common spelling variation)
    - collapses whitespace, lowercases
    """
    text = unicodedata.normalize("NFD", name)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[أإآ]", "ا", text)
    text = text.replace("ؤ", "و").replace("ئ", "ي")
    text = text.replace("ة", "ه")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


@dataclass(frozen=True)
class Contact:
    """A phone-book entry: display name + phone number."""

    name: str
    number: str

    @property
    def normalized_name(self) -> str:
        return normalize_arabic_name(self.name)

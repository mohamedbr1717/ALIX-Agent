"""DTO for the pack_context tool."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PackContextRequest:
    root: str = ""
    focus: list = field(default_factory=list)
    max_tokens: int = 4000
    max_files: int = 20

    def __post_init__(self):
        object.__setattr__(self, "root", str(self.root or ""))
        raw_focus = self.focus or []
        if isinstance(raw_focus, str):
            raw_focus = [raw_focus]
        clean = []
        for item in raw_focus:
            text = str(item or "").strip()[:60]
            if text and text not in clean and len(clean) < 10:
                clean.append(text)
        object.__setattr__(self, "focus", clean)
        try:
            tokens = int(self.max_tokens)
        except (TypeError, ValueError):
            tokens = 4000
        try:
            files = int(self.max_files)
        except (TypeError, ValueError):
            files = 20
        # Server clamps to 500..200000; we keep the same floor.
        object.__setattr__(self, "max_tokens", max(500, min(200000, tokens)))
        object.__setattr__(self, "max_files", max(1, min(200, files)))

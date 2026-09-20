from __future__ import annotations

from abc import ABC, abstractmethod


class AuthorizationPort(ABC):
    @abstractmethod
    def can_read_file(self, path: str) -> bool:
        raise NotImplementedError

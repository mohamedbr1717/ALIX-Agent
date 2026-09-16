from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional


class Memory:
    """
    نظام الذاكرة الدائمة لـ ALIX.

    المزايا:
    - Atomic Save
    - Backup تلقائي
    - Recovery عند تلف ملف الذاكرة
    - منع التكرار
    - Timestamp لكل ذاكرة
    - حدود للحجم
    - History محدود
    - Thread-safe
    - API متوافق مع ALIXAgent
    """

    MAX_FACTS = 500
    MAX_PREFERENCES = 300
    MAX_HISTORY = 100
    MAX_TEXT_LENGTH = 2000

    def __init__(self, path: Optional[str | Path] = None):

        self.path = Path(
            path
            or Path.home()
            / "ALIX-Agent"
            / "memory"
            / "memory.json"
        ).expanduser().resolve()

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.backup_path = self.path.with_suffix(
            ".json.bak"
        )

        self.lock = threading.RLock()

        if not self.path.exists():

            if self.backup_path.exists():
                self._restore_backup()

            else:
                self._save(
                    self._empty_memory()
                )

        else:
            # تحقق مبكر من سلامة الملف.
            # يجب التمييز بين primary صالح وprimary تالف،
            # لأن _load() يفشل بأمان بإرجاع memory فارغة.
            data = self._load_raw()

            if data is None:
                if not self._restore_backup():
                    self._save(
                        self._empty_memory()
                    )

    # ============================================================
    # Base structure
    # ============================================================

    @staticmethod
    def _empty_memory() -> dict:
        return {
            "version": 2,
            "facts": [],
            "preferences": [],
            "history": []
        }

    def _valid_structure(
        self,
        data: Any
    ) -> bool:

        if not isinstance(data, dict):
            return False

        return all(
            isinstance(data.get(key), list)
            for key in (
                "facts",
                "preferences",
                "history"
            )
        )

    # ============================================================
    # Sanitization
    # ============================================================

    # SECURITY FIX: add_history() persists raw user/assistant turns
    # to disk on every single round with NO confirmation gate (unlike
    # remember_fact, which requires user approval). If a person pastes
    # a password or API key into a request, it was written to
    # memory.json in plaintext and kept there for up to MAX_HISTORY
    # turns. This is a best-effort pattern screen, not a guarantee --
    # secrets that don't match a known shape will still pass through.
    # It reduces the common, high-confidence cases (cloud keys, private
    # key blocks, bearer tokens, "password=..." style assignments).
    _SECRET_PATTERNS = [
        # AWS access key IDs
        (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
        # OpenAI / Anthropic / generic vendor "sk-..." style keys
        (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
        # GitHub tokens
        (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
        # PEM-style private key blocks
        (
            re.compile(
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.DOTALL,
            ),
            "[REDACTED_PRIVATE_KEY]",
        ),
        # Bearer / JWT-style tokens
        (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b"), "Bearer [REDACTED_TOKEN]"),
        (
            re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
            "[REDACTED_JWT]",
        ),
        # key/secret/password/token = value assignments (common in
        # .env-style pasted config)
        (
            re.compile(
                r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*"
                r"['\"]?[A-Za-z0-9/+._-]{8,}['\"]?"
            ),
            r"\1=[REDACTED]",
        ),
    ]

    @classmethod
    def _redact_secrets(cls, text: str) -> str:
        for pattern, replacement in cls._SECRET_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def _sanitize_text(
        self,
        value: Any
    ) -> str:

        if value is None:
            return ""

        text = str(value).strip()

        if not text:
            return ""

        # منع null byte.
        text = text.replace("\x00", "")

        text = self._redact_secrets(text)

        return text[:self.MAX_TEXT_LENGTH]

    # ============================================================
    # Load
    # ============================================================

    def _load_raw(self) -> Optional[dict]:
        """Load primary memory while preserving corruption status."""

        with self.lock:
            try:
                data = json.loads(
                    self.path.read_text(
                        encoding="utf-8"
                    )
                )

                if not self._valid_structure(data):
                    return None

                data.setdefault("version", 1)
                return data

            except (
                json.JSONDecodeError,
                OSError,
                ValueError,
                TypeError,
            ):
                return None

    def _load(self) -> dict:

        with self.lock:

            try:

                with self.path.open(
                    "r",
                    encoding="utf-8"
                ) as file:

                    data = json.load(file)

                if not self._valid_structure(data):

                    return self._empty_memory()

                # ضمان وجود version.
                data.setdefault(
                    "version",
                    1
                )

                return data

            except (
                json.JSONDecodeError,
                OSError,
                ValueError,
                TypeError
            ):

                return self._empty_memory()

    # ============================================================
    # Atomic save
    # ============================================================

    def _restrict_permissions(self, path: Path) -> None:
        # SECURITY FIX: memory.json/.bak previously used default OS
        # permissions. Since memory.json can contain conversation
        # history and remembered facts, restrict it to the owning
        # user only. Best-effort: some filesystems (e.g. certain
        # Android storage backends) don't support chmod, so failures
        # here must never block a save.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _save(
        self,
        data: dict,
        backup_current: bool = True
    ) -> bool:

        with self.lock:

            temp_path = None

            try:

                self.path.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                # تنظيف البنية قبل الحفظ.
                data = self._normalize(data)

                fd, temp_name = tempfile.mkstemp(
                    prefix=".memory-",
                    suffix=".tmp",
                    dir=str(self.path.parent)
                )

                temp_path = Path(temp_name)

                with os.fdopen(
                    fd,
                    "w",
                    encoding="utf-8"
                ) as file:

                    json.dump(
                        data,
                        file,
                        ensure_ascii=False,
                        indent=2
                    )

                    file.flush()
                    os.fsync(
                        file.fileno()
                    )

                # Backup للنسخة الحالية.
                # أثناء Recovery لا ننسخ primary التالف
                # فوق الـ backup السليم.
                if backup_current and self.path.exists():

                    try:
                        shutil.copy2(
                            self.path,
                            self.backup_path
                        )
                        self._restrict_permissions(self.backup_path)
                    except OSError:
                        pass

                # استبدال ذري.
                os.replace(
                    temp_path,
                    self.path
                )

                self._restrict_permissions(self.path)

                temp_path = None

                return True

            except (
                OSError,
                TypeError,
                ValueError
            ):

                return False

            finally:

                if (
                    temp_path is not None
                    and temp_path.exists()
                ):
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

    # ============================================================
    # Normalize
    # ============================================================

    def _normalize(
        self,
        data: dict
    ) -> dict:

        if not isinstance(data, dict):
            data = self._empty_memory()

        facts = data.get(
            "facts",
            []
        )

        preferences = data.get(
            "preferences",
            []
        )

        history = data.get(
            "history",
            []
        )

        if not isinstance(facts, list):
            facts = []

        if not isinstance(
            preferences,
            list
        ):
            preferences = []

        if not isinstance(history, list):
            history = []

        return {
            "version": 2,
            "facts": facts[-self.MAX_FACTS:],
            "preferences": preferences[
                -self.MAX_PREFERENCES:
            ],
            "history": history[
                -self.MAX_HISTORY:
            ]
        }

    # ============================================================
    # Recovery
    # ============================================================

    def _restore_backup(self) -> bool:

        with self.lock:

            if not self.backup_path.exists():
                return False

            try:

                backup_data = json.loads(
                    self.backup_path.read_text(
                        encoding="utf-8"
                    )
                )

                if not self._valid_structure(
                    backup_data
                ):
                    return False

                return self._save(
                    backup_data,
                    backup_current=False
                )

            except Exception:
                return False

    # ============================================================
    # Facts
    # ============================================================

    def add_fact(
        self,
        fact: Any
    ) -> bool:

        fact = self._sanitize_text(
            fact
        )

        if not fact:
            return False

        with self.lock:

            data = self._load()

            for item in data["facts"]:

                if (
                    isinstance(item, dict)
                    and item.get("text") == fact
                ):
                    return True

                if item == fact:
                    return True

            data["facts"].append(
                {
                    "text": fact,
                    "created_at": int(
                        time.time()
                    )
                }
            )

            return self._save(data)

    # ============================================================
    # Preferences
    # ============================================================

    def add_preference(
        self,
        preference: Any
    ) -> bool:

        preference = self._sanitize_text(
            preference
        )

        if not preference:
            return False

        with self.lock:

            data = self._load()

            for item in data[
                "preferences"
            ]:

                if (
                    isinstance(item, dict)
                    and item.get("text")
                    == preference
                ):
                    return True

                if item == preference:
                    return True

            data["preferences"].append(
                {
                    "text": preference,
                    "created_at": int(
                        time.time()
                    )
                }
            )

            return self._save(data)

    # ============================================================
    # History
    # ============================================================

    def add_history(
        self,
        role: Any,
        content: Any
    ) -> bool:

        role = self._sanitize_text(
            role
        )

        content = self._sanitize_text(
            content
        )

        if not role or not content:
            return False

        with self.lock:

            data = self._load()

            data["history"].append(
                {
                    "role": role,
                    "content": content,
                    "timestamp": int(
                        time.time()
                    )
                }
            )

            data["history"] = data[
                "history"
            ][-self.MAX_HISTORY:]

            return self._save(data)

    # ============================================================
    # Context
    # ============================================================

    def get_context(self) -> dict:

        with self.lock:

            data = self._load()

            return {
                "facts": data.get(
                    "facts",
                    []
                ),
                "preferences": data.get(
                    "preferences",
                    []
                ),
                "history": data.get(
                    "history",
                    []
                )
            }

    # ============================================================
    # Search memory
    # ============================================================

    def search(
        self,
        query: str,
        limit: int = 10
    ) -> list[dict]:

        query = self._sanitize_text(
            query
        ).lower()

        if not query:
            return []

        results = []

        with self.lock:

            data = self._load()

            for category in (
                "facts",
                "preferences"
            ):

                for item in data.get(
                    category,
                    []
                ):

                    if isinstance(
                        item,
                        dict
                    ):
                        text = str(
                            item.get(
                                "text",
                                ""
                            )
                        )

                    else:
                        text = str(item)

                    if query in text.lower():

                        results.append(
                            {
                                "type": category,
                                "text": text
                            }
                        )

                        if len(results) >= limit:
                            return results

        return results

    # ============================================================
    # Clear history
    # ============================================================

    def clear_history(self) -> bool:

        with self.lock:

            data = self._load()

            data["history"] = []

            return self._save(data)

    # ============================================================
    # Clear everything
    # ============================================================

    def clear_all(self) -> bool:

        with self.lock:

            return self._save(
                self._empty_memory()
            )

    # ============================================================
    # Statistics
    # ============================================================

    def stats(self) -> dict:

        with self.lock:

            data = self._load()

            return {
                "version": data.get(
                    "version",
                    2
                ),
                "facts": len(
                    data.get(
                        "facts",
                        []
                    )
                ),
                "preferences": len(
                    data.get(
                        "preferences",
                        []
                    )
                ),
                "history": len(
                    data.get(
                        "history",
                        []
                    )
                ),
                "path": str(
                    self.path
                ),
                "backup_exists": (
                    self.backup_path.exists()
                )
            }

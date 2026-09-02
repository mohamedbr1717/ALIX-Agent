from __future__ import annotations

import json
import os
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
            data = self._load()

            if not self._valid_structure(data):
                self._restore_backup()

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

        return text[:self.MAX_TEXT_LENGTH]

    # ============================================================
    # Load
    # ============================================================

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

    def _save(
        self,
        data: dict
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
                if self.path.exists():

                    try:
                        shutil.copy2(
                            self.path,
                            self.backup_path
                        )
                    except OSError:
                        pass

                # استبدال ذري.
                os.replace(
                    temp_path,
                    self.path
                )

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
                    backup_data
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

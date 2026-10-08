"""SafeExecutor _FilesMixin (private)."""
from __future__ import annotations

import time
from typing import Optional
class _FilesMixin:
    """Methods moved verbatim."""

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "read_file",
                started,
                False,
                "المسار غير مسموح أو يشير إلى ملف حساس.",
            ).to_dict()

        if not target.exists():
            return self._base_result(
                "read_file",
                started,
                False,
                "الملف غير موجود.",
            ).to_dict()

        if not target.is_file():
            return self._base_result(
                "read_file",
                started,
                False,
                "المسار ليس ملفًا.",
            ).to_dict()

        try:
            start = max(1, int(start_line))

            if end_line is None:
                end = None
            else:
                end = max(start, int(end_line))

            # Stream the file line-by-line.  Never materialize the complete
            # file or its complete splitlines() representation in memory.
            line_count = 0
            selected_line_count = 0
            output_parts = []
            output_chars = 0
            previous_selected = False

            with target.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                truncated_by_length = False

                for raw_line in handle:
                    line_count += 1

                    if line_count < start:
                        continue

                    if end is not None and line_count > end:
                        continue

                    selected_line_count += 1

                    # Preserve the historical "\n".join(...) contract
                    # without storing all selected lines.
                    line = raw_line.rstrip("\r\n")

                    prefix = "\n" if previous_selected else ""
                    previous_selected = True

                    remaining = self.max_output - output_chars
                    if remaining <= 0:
                        truncated_by_length = True
                        continue

                    piece = prefix + line
                    if len(piece) > remaining:
                        piece = piece[:remaining]
                        truncated_by_length = True

                    output_parts.append(piece)
                    output_chars += len(piece)

            content = "".join(output_parts)

            evidence = {
                "path": str(target.relative_to(self.policy.workspace)),
                "exists": True,
                "is_file": True,
                "line_count": line_count,
                "returned_lines": selected_line_count,
                "size_bytes": target.stat().st_size,
                "streamed": True,
                # FIX: previously compared byte-size (includes trailing
                # newlines) against character count of newline-stripped
                # content -- that mismatch made almost every file with a
                # trailing newline report output_truncated=True even
                # when nothing was actually cut for length. Now this
                # reflects only whether the max_output character cap
                # actually cut something during the loop above.
                "output_truncated": truncated_by_length,
            }

            return self._base_result(
                "read_file",
                started,
                True,
                "تمت قراءة الملف.",
                stdout=content,
                evidence=evidence,
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "read_file",
                started,
                False,
                f"فشل قراءة الملف: {exc}",
            ).to_dict()


    def write_file(
        self,
        path: str,
        content: str,
    ) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "write_file",
                started,
                False,
                "المسار غير مسموح أو يشير إلى ملف حساس.",
            ).to_dict()

        if not isinstance(content, str):
            return self._base_result(
                "write_file",
                started,
                False,
                "محتوى الملف يجب أن يكون نصًا.",
            ).to_dict()

        try:
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            # حفظ نسخة احتياطية قبل الكتابة إذا كان الملف موجودًا.
            backup_path = None

            if target.exists() and target.is_file():
                backup_path = target.with_name(
                    target.name + ".alix-backup"
                )

                with target.open("rb") as source, backup_path.open("wb") as backup:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        backup.write(chunk)

            target.write_text(
                content,
                encoding="utf-8",
            )

            # تحقق مستقل بعد الكتابة.
            exists = target.exists()
            is_file = target.is_file()

            size = target.stat().st_size if is_file else 0

            verified = (
                exists
                and is_file
                and size == len(content.encode("utf-8"))
            )

            evidence = {
                "path": str(target.relative_to(self.policy.workspace)),
                "exists_after_write": exists,
                "is_file_after_write": is_file,
                "size_bytes": size,
                "verified": verified,
                "backup_created": bool(backup_path),
            }

            if backup_path:
                evidence["backup"] = str(
                    backup_path.relative_to(self.policy.workspace)
                )

            return self._base_result(
                "write_file",
                started,
                verified,
                "تمت كتابة الملف والتحقق منه."
                if verified
                else "تمت محاولة الكتابة ولكن فشل التحقق.",
                evidence=evidence,
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "write_file",
                started,
                False,
                f"فشل كتابة الملف: {exc}",
            ).to_dict()


    def create_directory(self, path: str) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "create_directory",
                started,
                False,
                "المسار غير مسموح.",
            ).to_dict()

        try:
            target.mkdir(
                parents=True,
                exist_ok=True,
            )

            verified = target.exists() and target.is_dir()

            return self._base_result(
                "create_directory",
                started,
                verified,
                "تم إنشاء المجلد والتحقق منه."
                if verified
                else "فشل التحقق من إنشاء المجلد.",
                evidence={
                    "path": str(
                        target.relative_to(self.policy.workspace)
                    ),
                    "exists": target.exists(),
                    "is_directory": target.is_dir(),
                    "verified": verified,
                },
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "create_directory",
                started,
                False,
                f"فشل إنشاء المجلد: {exc}",
            ).to_dict()


    def delete_file(self, path: str) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "delete_file",
                started,
                False,
                "المسار غير مسموح أو حساس.",
            ).to_dict()

        if not target.exists():
            return self._base_result(
                "delete_file",
                started,
                False,
                "الملف غير موجود.",
            ).to_dict()

        if not target.is_file():
            return self._base_result(
                "delete_file",
                started,
                False,
                "الحذف مسموح للملفات فقط.",
            ).to_dict()

        try:
            backup_path = target.with_name(
                target.name + ".alix-delete-backup"
            )

            with target.open("rb") as source, backup_path.open("wb") as backup:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    backup.write(chunk)

            target.unlink()

            verified = not target.exists()

            return self._base_result(
                "delete_file",
                started,
                verified,
                "تم حذف الملف والتحقق من الحذف."
                if verified
                else "فشل التحقق من الحذف.",
                evidence={
                    "path": str(
                        target.relative_to(self.policy.workspace)
                    ),
                    "deleted": verified,
                    "backup": str(
                        backup_path.relative_to(self.policy.workspace)
                    ),
                    "rollback_available": backup_path.exists(),
                },
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "delete_file",
                started,
                False,
                f"فشل حذف الملف: {exc}",
            ).to_dict()


    def search_files(
        self,
        pattern: str,
        path: str = ".",
        max_matches: int = 20,
    ) -> dict:

        started = time.monotonic()

        if not self.policy.validate_search_pattern(pattern):
            return self._base_result(
                "search_files",
                started,
                False,
                "نمط البحث غير صالح أو طويل جدًا.",
            ).to_dict()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "search_files",
                started,
                False,
                "مسار البحث غير مسموح.",
            ).to_dict()

        if not target.exists():
            return self._base_result(
                "search_files",
                started,
                False,
                "مسار البحث غير موجود.",
            ).to_dict()

        matches = []

        try:
            files = (
                [target]
                if target.is_file()
                else target.rglob("*")
            )

            for file_path in files:

                if len(matches) >= max_matches:
                    break

                if not file_path.is_file():
                    continue

                if self.policy.is_sensitive_path(file_path):
                    continue

                try:
                    with file_path.open(
                        "r",
                        encoding="utf-8",
                        errors="ignore",
                    ) as handle:
                        for line_number, line in enumerate(handle, 1):
                            if pattern.lower() not in line.lower():
                                continue

                            relative = str(
                                file_path.relative_to(
                                    self.policy.workspace
                                )
                            )

                            matches.append(
                                {
                                    "file": relative,
                                    "line": line_number,
                                    "content": self._truncate(
                                        line.strip(),
                                        500,
                                    ),
                                }
                            )

                            if len(matches) >= max_matches:
                                break
                except Exception:
                    continue

            return self._base_result(
                "search_files",
                started,
                True,
                "اكتمل البحث.",
                evidence={
                    "pattern": pattern,
                    "matches": matches,
                    "count": len(matches),
                    "truncated": len(matches) >= max_matches,
                },
            ).to_dict()

        except Exception as exc:
            return self._base_result(
                "search_files",
                started,
                False,
                f"فشل البحث: {exc}",
            ).to_dict()


    def verify_file(
        self,
        path: str,
    ) -> dict:

        started = time.monotonic()

        target = self.policy.validate_file_path(path)

        if target is None:
            return self._base_result(
                "verify_file",
                started,
                False,
                "المسار غير مسموح.",
            ).to_dict()

        exists = target.exists()
        is_file = target.is_file() if exists else False

        evidence = {
            "path": str(
                target.relative_to(
                    self.policy.workspace
                )
            ),
            "exists": exists,
            "is_file": is_file,
            "size_bytes": (
                target.stat().st_size
                if is_file
                else 0
            ),
            "verified": exists and is_file,
        }

        return self._base_result(
            "verify_file",
            started,
            exists and is_file,
            "تم التحقق من الملف."
            if exists and is_file
            else "الملف غير موجود.",
            evidence=evidence,
        ).to_dict()



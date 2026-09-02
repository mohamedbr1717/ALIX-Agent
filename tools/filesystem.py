from pathlib import Path
import subprocess
import sys


class FileSystemTools:
    """
    أدوات الملفات الخاصة بـ ALIX.

    كل عمليات الملفات محصورة داخل:
        ~/ALIX-Agent/workspace
    """

    MAX_READ_SIZE = 2 * 1024 * 1024
    MAX_WRITE_SIZE = 2 * 1024 * 1024
    COMMAND_TIMEOUT = 60

    def __init__(self, policy):
        self.policy = policy

    # ========================================================
    # PATH
    # ========================================================

    def _path(self, path):
        """
        تحويل المسار والتحقق من أنه داخل workspace.
        """

        resolved = self.policy.resolve_path(path)

        if resolved is None:
            raise PermissionError(
                "المسار خارج مساحة ALIX."
            )

        return resolved

    # ========================================================
    # LIST
    # ========================================================

    def list_files(
        self,
        path=".",
        all=False
    ):
        base = self._path(path)

        if not base.exists():

            return {
                "ok": False,
                "error": "المسار غير موجود."
            }

        if not base.is_dir():

            return {
                "ok": False,
                "error": "المسار ليس مجلدًا."
            }

        items = []

        try:

            entries = sorted(
                base.iterdir(),
                key=lambda x: (
                    not x.is_dir(),
                    x.name.lower()
                )
            )

            for item in entries:

                if (
                    not all
                    and item.name.startswith(".")
                ):
                    continue

                try:

                    item_type = (
                        "directory"
                        if item.is_dir()
                        else "file"
                    )

                    size = (
                        item.stat().st_size
                        if item.is_file()
                        else None
                    )

                except OSError:

                    item_type = "unknown"
                    size = None

                items.append({
                    "name": item.name,
                    "type": item_type,
                    "size": size
                })

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

        try:

            relative = base.relative_to(
                self.policy.workspace
            )

            relative_path = (
                str(relative)
                if str(relative) != "."
                else "."
            )

        except ValueError:

            relative_path = "."

        return {
            "ok": True,
            "path": relative_path,
            "items": items[:500]
        }

    # ========================================================
    # READ
    # ========================================================

    def read_file(self, path):

        base = self._path(path)

        if not base.exists():

            return {
                "ok": False,
                "error": "الملف غير موجود."
            }

        if not base.is_file():

            return {
                "ok": False,
                "error": "المسار ليس ملفًا."
            }

        try:

            size = base.stat().st_size

        except OSError as e:

            return {
                "ok": False,
                "error": str(e)
            }

        if size > self.MAX_READ_SIZE:

            return {
                "ok": False,
                "error": (
                    f"الملف أكبر من الحد المسموح "
                    f"({self.MAX_READ_SIZE} bytes)."
                )
            }

        try:

            content = base.read_text(
                encoding="utf-8",
                errors="replace"
            )

            return {
                "ok": True,
                "path": str(
                    base.relative_to(
                        self.policy.workspace
                    )
                ),
                "content": content,
                "bytes": size
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    # ========================================================
    # CREATE DIRECTORY
    # ========================================================

    def create_directory(self, path):

        base = self._path(path)

        try:

            base.mkdir(
                parents=True,
                exist_ok=True
            )

            return {
                "ok": True,
                "path": str(
                    base.relative_to(
                        self.policy.workspace
                    )
                )
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    # ========================================================
    # WRITE
    # ========================================================

    def write_file(
        self,
        path,
        content
    ):

        base = self._path(path)

        if not isinstance(
            content,
            str
        ):

            return {
                "ok": False,
                "error": "content يجب أن يكون نصًا."
            }

        encoded = content.encode(
            "utf-8"
        )

        if len(encoded) > self.MAX_WRITE_SIZE:

            return {
                "ok": False,
                "error": (
                    f"المحتوى أكبر من الحد المسموح "
                    f"({self.MAX_WRITE_SIZE} bytes)."
                )
            }

        try:

            base.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            base.write_text(
                content,
                encoding="utf-8"
            )

            return {
                "ok": True,
                "path": str(
                    base.relative_to(
                        self.policy.workspace
                    )
                ),
                "bytes": len(encoded)
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    # ========================================================
    # DELETE
    # ========================================================

    def delete_file(self, path):

        base = self._path(path)

        if base == self.policy.workspace:

            return {
                "ok": False,
                "error": (
                    "لا يمكن حذف workspace."
                )
            }

        if not base.exists():

            return {
                "ok": False,
                "error": "الملف غير موجود."
            }

        if not base.is_file():

            return {
                "ok": False,
                "error": (
                    "يمكن حذف الملفات فقط، "
                    "وليس المجلدات."
                )
            }

        try:

            base.unlink()

            return {
                "ok": True,
                "deleted": str(
                    base.relative_to(
                        self.policy.workspace
                    )
                )
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    # ========================================================
    # RUN PYTHON
    # ========================================================

    def run_python(
        self,
        path,
        args=None
    ):

        base = self._path(path)

        if base.suffix.lower() != ".py":

            return {
                "ok": False,
                "error": (
                    "يجب أن يكون الملف "
                    "Python (.py)."
                )
            }

        if not base.is_file():

            return {
                "ok": False,
                "error": "ملف Python غير موجود."
            }

        if args is None:
            args = []

        if not isinstance(
            args,
            list
        ):

            return {
                "ok": False,
                "error": (
                    "args يجب أن تكون قائمة."
                )
            }

        safe_args = []

        for value in args:

            if not isinstance(
                value,
                (str, int, float)
            ):

                return {
                    "ok": False,
                    "error": (
                        "كل عنصر في args "
                        "يجب أن يكون قيمة بسيطة."
                    )
                }

            safe_args.append(
                str(value)
            )

        command = [
            sys.executable,
            str(base)
        ]

        command.extend(
            safe_args
        )

        try:

            result = subprocess.run(
                command,
                cwd=str(
                    self.policy.workspace
                ),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.COMMAND_TIMEOUT
            )

            return {
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:]
            }

        except subprocess.TimeoutExpired:

            return {
                "ok": False,
                "error": (
                    "انتهت مهلة تشغيل Python."
                )
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

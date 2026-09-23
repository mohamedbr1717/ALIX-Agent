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
        import time
        from core.executor import ExecutionResult

        started = time.monotonic()

        try:
            base = self._path(path)
        except PermissionError as exc:
            return ExecutionResult(
                ok=False,
                action="list_files",
                message=str(exc),
                duration=time.monotonic() - started,
            ).to_dict()

        if not base.exists():
            return ExecutionResult(
                ok=False,
                action="list_files",
                message="المسار غير موجود.",
                duration=time.monotonic() - started,
            ).to_dict()

        if not base.is_dir():
            return ExecutionResult(
                ok=False,
                action="list_files",
                message="المسار ليس مجلدًا.",
                duration=time.monotonic() - started,
            ).to_dict()

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

                # SECURITY FIX: this method previously listed every
                # non-dotfile entry unfiltered, unlike the list_files
                # path actually used in core/agent.py._execute_tool_body,
                # which skips anything self.policy.is_sensitive_path()
                # flags (credentials.json, id_rsa, *.pem, etc. -- none
                # of which necessarily start with a dot). That made
                # this implementation leak sensitive filenames if it
                # was ever wired back in. Both list_files
                # implementations must apply the same filter.
                if self.policy.is_sensitive_path(item):
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
            return ExecutionResult(
                ok=False,
                action="list_files",
                message=str(e),
                duration=time.monotonic() - started,
            ).to_dict()

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

        # SCHEMA FIX: this method used to return its own ad-hoc shape
        # ({"ok", "error"} / {"ok", "path", "items"}), the only tool
        # in the registry that didn't match the canonical
        # ExecutionResult contract every SafeExecutor method returns
        # (ok/action/message/stdout/stderr/returncode/evidence/duration).
        # Structured data now lives under evidence, matching the
        # convention used by system_info and every other tool.
        return ExecutionResult(
            ok=True,
            action="list_files",
            message="تم سرد الملفات.",
            duration=time.monotonic() - started,
            evidence={
                "path": relative_path,
                "items": items[:500],
                "count": len(items),
            },
        ).to_dict()

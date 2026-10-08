"""SafeExecutor _ProcessMixin (private)."""
from __future__ import annotations

import os
import subprocess
from typing import Any
class _ProcessMixin:
    """Methods moved verbatim."""

    @staticmethod
    def _truncate(value: Any, limit: int) -> str:
        if value is None:
            return ""

        text = str(value)

        if len(text) <= limit:
            return text

        marker = "\n...[تم اقتطاع المخرجات]..."

        if limit <= len(marker):
            return marker[:limit]

        return text[:limit - len(marker)] + marker


    def _run_bounded_process(
        self,
        argv,
        *,
        cwd,
        env,
        timeout,
        max_stdout=None,
        max_stderr=None,
    ):
        """Run a child process with continuously drained bounded output."""

        import os
        import signal
        import threading
        from collections import deque

        stdout_limit = (
            self.max_output
            if max_stdout is None
            else max(1, int(max_stdout))
        )

        stderr_limit = (
            2000
            if max_stderr is None
            else max(1, int(max_stderr))
        )

        stdout_chunks = deque()
        stderr_chunks = deque()

        stdout_bytes = 0
        stderr_bytes = 0

        lock = threading.Lock()

        def drain(stream, chunks, limit, stream_name):
            nonlocal stdout_bytes, stderr_bytes

            try:
                while True:
                    data = stream.read(65536)

                    if not data:
                        break

                    if isinstance(data, str):
                        data = data.encode(
                            "utf-8",
                            "replace",
                        )

                    with lock:
                        if stream_name == "stdout":
                            stdout_bytes += len(data)
                        else:
                            stderr_bytes += len(data)

                        kept = sum(len(x) for x in chunks)
                        remaining = limit - kept

                        if remaining > 0:
                            chunks.append(
                                data[:remaining]
                            )

            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        proc = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=(
                os.name == "posix"
            ),
        )

        stdout_thread = threading.Thread(
            target=drain,
            args=(
                proc.stdout,
                stdout_chunks,
                stdout_limit,
                "stdout",
            ),
            daemon=True,
        )

        stderr_thread = threading.Thread(
            target=drain,
            args=(
                proc.stderr,
                stderr_chunks,
                stderr_limit,
                "stderr",
            ),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        timed_out = False

        try:
            proc.wait(
                timeout=max(
                    1,
                    int(timeout),
                )
            )

        except subprocess.TimeoutExpired:
            timed_out = True

            try:
                if os.name == "posix":
                    os.killpg(
                        proc.pid,
                        signal.SIGKILL,
                    )
                else:
                    proc.kill()

            except ProcessLookupError:
                pass

            proc.wait()

        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        stdout = b"".join(
            stdout_chunks
        ).decode(
            "utf-8",
            "replace",
        )

        stderr = b"".join(
            stderr_chunks
        ).decode(
            "utf-8",
            "replace",
        )

        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "stdout_truncated": (
                stdout_bytes > stdout_limit
            ),
            "stderr_truncated": (
                stderr_bytes > stderr_limit
            ),
            "timed_out": timed_out,
        }


    def _safe_environment(self) -> dict:
        """
        بيئة تنفيذ محدودة.

        لا نقوم هنا بحذف PATH أو HOME لأن Python وTermux
        يحتاجان إلى بيئة أساسية للعمل، لكننا نمنع تمرير
        متغيرات سرية معروفة إلى العمليات التي ينشئها ALIX.
        """

        env = dict(os.environ)

        sensitive_prefixes = (
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "AWS_ACCESS_KEY",
            "AWS_SECRET",
            "GITHUB_TOKEN",
            "GH_TOKEN",

            # Termux dynamic-linker injection must not cross the
            # subprocess/sandbox boundary.
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
        )

        for key in list(env.keys()):
            upper = key.upper()

            if any(
                upper == prefix or upper.startswith(prefix + "_")
                for prefix in sensitive_prefixes
            ):
                env.pop(key, None)

        return env



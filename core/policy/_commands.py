"""Policy _CommandsMixin (private)."""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Optional
class _CommandsMixin:
    """Methods moved verbatim."""

    def parse_command(
        self,
        command: str,
    ) -> Optional[list[str]]:

        if not isinstance(command, str):
            return None

        command = command.strip()

        if not command:
            return None

        if len(command) > self.max_command_length:
            return None

        if "\x00" in command:
            return None

        # Reject dangerous syntax before shlex parsing.
        for pattern in self.blocked_patterns:
            if re.search(
                pattern,
                command,
                flags=re.IGNORECASE,
            ):
                return None

        try:
            parts = shlex.split(
                command,
                posix=True,
            )
        except ValueError:
            return None

        if not parts:
            return None

        if len(parts) > self.max_command_args:
            return None

        for part in parts:
            if len(part) > self.max_argument_length:
                return None

            if "\x00" in part:
                return None

        return parts


    def _command_has_forbidden_path(
        self,
        parts: list[str],
    ) -> bool:

        for arg in parts[1:]:
            if not isinstance(arg, str):
                return True

            if "\x00" in arg:
                return True

            # Absolute system locations.
            if re.search(
                r"^(?:/etc|/proc|/sys|/dev|/root|/system|/vendor)(?:/|$)",
                arg,
                flags=re.IGNORECASE,
            ):
                return True

            if arg.startswith("/data/data"):
                return True

            if arg.startswith("/data/user"):
                return True

            # Explicit traversal.
            if ".." in Path(arg).parts:
                return True

        return False


    def _git_command_allowed(
        self,
        parts: list[str],
    ) -> bool:
        if not isinstance(parts, list):
            return False

        if len(parts) < 2:
            return False

        action = parts[1]

        if action not in self.allowed_git_commands:
            return False

        blocked_exact = {
            "-c",
            "--config",
            "--exec-path",
            "--git-dir",
            "--work-tree",
            "--super-prefix",
            "--namespace",
            "--upload-pack",
            "--receive-pack",
            "--paginate",
            "--no-pager",
            "--help",
            "-h",
        }

        blocked_prefixes = (
            "--config=",
            "--exec-path=",
            "--git-dir=",
            "--work-tree=",
            "--super-prefix=",
            "--namespace=",
            "--upload-pack=",
            "--receive-pack=",
        )

        for token in parts[1:]:
            if not isinstance(token, str):
                return False

            lowered = token.lower()

            if token in self.blocked_git_tokens:
                return False

            if token in blocked_exact:
                return False

            if lowered.startswith(blocked_prefixes):
                return False

            if token.startswith("/"):
                return False

            if ".." in Path(token).parts:
                return False

            if any(
                char in token
                for char in ("`", "$", ";", "|", ">", "<")
            ):
                return False

        return True


    def command_allowed(
        self,
        command: str,
    ) -> bool:
        """
        Final command authorization.
        """

        parts = self.parse_command(command)

        if not parts:
            return False

        executable = Path(parts[0]).name.lower()

        if executable in self.blocked_commands:
            return False

        if executable not in self.allowed_commands:
            return False

        if self._command_has_forbidden_path(parts):
            return False

        # ---------------------------------------------------------
        # Sensitive file protection
        # ---------------------------------------------------------

        if executable in {
            "cat",
            "head",
            "tail",
            "less",
            "more",
            "file",
        }:
            for argument in parts[1:]:
                if not isinstance(argument, str):
                    return False

                if argument.startswith("-"):
                    continue

                target = self.resolve_path(argument)

                if target is None:
                    return False

                if self.is_sensitive_path(target):
                    return False

        # ---------------------------------------------------------
        # Python restrictions
        # ---------------------------------------------------------
        #
        # SECURITY FIX: previously "python <script>.py" could be run
        # via run_command() even when the "run_python" capability was
        # disabled (capabilities["run_python"] = False by default).
        # This let the entire path/command allowlist be bypassed by
        # writing an arbitrary .py file (write_file has no content
        # filtering) and then executing it -- the spawned interpreter
        # is a full, unsandboxed Python process (no seccomp, no
        # chroot, no restricted user), so any command-level protection
        # is meaningless once arbitrary Python code is running.
        #
        # Executing Python is now gated behind the same explicit
        # capability flag used by the dedicated run_python() tool, so
        # both entry points share one on/off switch and one policy.

        if executable in {"python", "python3"}:

            if not self.capability_allowed("run_python"):
                return False

            if "-c" in parts:
                return False

            if "-m" in parts:
                return False

            if "-i" in parts:
                return False

            if len(parts) < 2:
                return False

            script = parts[1]

            if not script.lower().endswith(".py"):
                return False

            try:
                target = Path(script)

                if target.is_absolute():
                    return False

                if ".." in target.parts:
                    return False

                resolved = (
                    self.workspace / target
                ).resolve(strict=False)

                if not self.path_allowed(resolved):
                    return False

                if self.is_sensitive_path(resolved):
                    return False

            except (
                OSError,
                RuntimeError,
                ValueError,
            ):
                return False

        # ---------------------------------------------------------
        # Git restrictions
        # ---------------------------------------------------------

        if executable == "git":
            return self._git_command_allowed(parts)

        return True



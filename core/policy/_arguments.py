"""Policy _ArgumentsMixin (private)."""
from __future__ import annotations

from pathlib import Path
class _ArgumentsMixin:
    """Methods moved verbatim."""

    def validate_search_pattern(self, pattern: str) -> bool:
        """
        التحقق من نمط البحث قبل التنفيذ.
        """
        if not isinstance(pattern, str):
            return False

        if not pattern:
            return False

        if len(pattern) > self.max_search_pattern_length:
            return False

        if "\x00" in pattern:
            return False

        return True


    def validate_tool_arguments(
        self,
        tool_name: str,
        arguments: dict,
    ) -> bool:
        """
        Strict tool argument boundary.

        Security properties:
        - Reject non-dict arguments.
        - Reject unknown argument names.
        - Enforce required arguments.
        - Enforce exact Python types.
        - Reject bool where int is expected.
        - Validate path boundaries.
        - Validate command restrictions.
        - Validate Python script restrictions.
        """

        if not isinstance(tool_name, str):
            return False

        if not self.tool_allowed(tool_name):
            return False

        if not isinstance(arguments, dict):
            return False

        schema = self.tool_argument_schema.get(tool_name)

        if schema is None:
            return False

        allowed = schema["allowed"]
        required = schema["required"]

        argument_names = set(arguments.keys())

        # Reject unknown arguments.
        if not argument_names.issubset(allowed):
            return False

        # Reject missing required arguments.
        if not required.issubset(argument_names):
            return False

        # Generic argument limits.
        if len(arguments) > 16:
            return False

        for key, value in arguments.items():

            if not isinstance(key, str):
                return False

            if len(key) > 100:
                return False

            if isinstance(value, str):
                if len(value) > self.max_argument_length:
                    return False

                if "\x00" in value:
                    return False

        # Exact argument types.
        expected_types = {
            "list_files": {
                "path": str,
            },
            "read_file": {
                "path": str,
                "start_line": int,
                "end_line": int,
            },
            "write_file": {
                "path": str,
                "content": str,
            },
            "create_directory": {
                "path": str,
            },
            "delete_file": {
                "path": str,
            },
            "search_files": {
                "pattern": str,
                "path": str,
                "max_matches": int,
            },
            "run_python": {
                "script_path": str,
            },
            "run_command": {
                "command": str,
            },
            "remember_fact": {
                "fact": str,
                "is_preference": bool,
            },
            "verify_file": {
                "path": str,
            },
            "web_search": {
                "query": str,
                "max_results": int,
            },
            "web_fetch": {
                "url": str,
                "max_chars": int,
            },
            "phone_call": {
                "number": str,
            },
            "send_sms": {
                "number": str,
                "message": str,
            },
            "notify": {
                "title": str,
                "content": str,
            },
            "repo_map": {
                "root": str,
                "max_depth": int,
                "max_entries": int,
            },
            "search_code": {
                "query": str,
                "root": str,
                "max_results": int,
                "case_sensitive": bool,
            },
            "pack_context": {
                "root": str,
                "focus": list,
                "max_tokens": int,
                "max_files": int,
            },
        }

        for key, expected_type in expected_types.get(
            tool_name,
            {}
        ).items():

            if key not in arguments:
                continue

            value = arguments[key]

            # Exact type check.
            # This intentionally rejects bool as an int.
            if type(value) is not expected_type:
                return False

        # ---------------------------------------------------------
        # File path validation
        # ---------------------------------------------------------

        path_tools = {
            "list_files",
            "read_file",
            "write_file",
            "create_directory",
            "delete_file",
            "search_files",
            "verify_file",
        }

        if tool_name in path_tools:

            # list_files and search_files have optional paths.
            path = arguments.get("path", ".")

            target = self.resolve_path(path)

            if target is None:
                return False

            if not self.path_allowed(target):
                return False

            if self.is_sensitive_path(target):
                return False

        # ---------------------------------------------------------
        # read_file line validation
        # ---------------------------------------------------------

        if tool_name == "read_file":

            start_line = arguments.get("start_line", 1)
            end_line = arguments.get("end_line")

            if type(start_line) is not int:
                return False

            if start_line < 1:
                return False

            if end_line is not None:

                if type(end_line) is not int:
                    return False

                if end_line < start_line:
                    return False

        # ---------------------------------------------------------
        # write_file validation
        # ---------------------------------------------------------

        if tool_name == "write_file":

            path = arguments.get("path")
            content = arguments.get("content")

            if not isinstance(path, str):
                return False

            if not path:
                return False

            if len(path) > self.max_path_length:
                return False

            if not isinstance(content, str):
                return False

        # ---------------------------------------------------------
        # create_directory
        # ---------------------------------------------------------

        if tool_name == "create_directory":

            path = arguments.get("path")

            if not isinstance(path, str):
                return False

            if not path:
                return False

            if len(path) > self.max_path_length:
                return False

        # ---------------------------------------------------------
        # delete_file
        # ---------------------------------------------------------

        if tool_name == "delete_file":

            path = arguments.get("path")

            if not isinstance(path, str):
                return False

            if not path:
                return False

            if len(path) > self.max_path_length:
                return False

        # ---------------------------------------------------------
        # search_files
        # ---------------------------------------------------------

        if tool_name == "search_files":

            pattern = arguments.get("pattern")

            if not isinstance(pattern, str):
                return False

            if not pattern:
                return False

            if len(pattern) > self.max_search_pattern_length:
                return False

            if "\x00" in pattern:
                return False

            max_matches = arguments.get(
                "max_matches",
                self.max_search_matches,
            )

            if type(max_matches) is not int:
                return False

            if (
                max_matches < 1
                or max_matches > self.max_search_matches
            ):
                return False

        # ---------------------------------------------------------
        # remember_fact
        # ---------------------------------------------------------

        if tool_name == "remember_fact":

            fact = arguments.get("fact")

            if not isinstance(fact, str):
                return False

            if not fact.strip():
                return False

            if len(fact) > self.max_argument_length:
                return False

            is_preference = arguments.get(
                "is_preference",
                False,
            )

            if type(is_preference) is not bool:
                return False

        # ---------------------------------------------------------
        # run_command
        # ---------------------------------------------------------

        if tool_name == "run_command":

            command = arguments.get("command")

            if not isinstance(command, str):
                return False

            if not command:
                return False

            if not self.command_allowed(command):
                return False

        # ---------------------------------------------------------
        # run_python
        # ---------------------------------------------------------

        if tool_name == "run_python":

            script_path = arguments.get("script_path")

            if not isinstance(script_path, str):
                return False

            if not script_path:
                return False

            if len(script_path) > self.max_path_length:
                return False

            if "\x00" in script_path:
                return False

            if Path(script_path).is_absolute():
                return False

            if ".." in Path(script_path).parts:
                return False

            target = self.resolve_path(script_path)

            if target is None:
                return False

            if not self.path_allowed(target):
                return False

            if self.is_sensitive_path(target):
                return False

            if target.suffix.lower() != ".py":
                return False

        return True


    def validate_command_arguments(
        self,
        arguments: dict,
    ) -> bool:
        """
        Validate generic tool arguments.
        """

        if not isinstance(arguments, dict):
            return False

        if len(arguments) > 16:
            return False

        for key, value in arguments.items():

            if not isinstance(key, str):
                return False

            if len(key) > 100:
                return False

            if isinstance(value, str):

                if len(value) > 2_000_000:
                    return False

                if "\x00" in value:
                    return False

        return True



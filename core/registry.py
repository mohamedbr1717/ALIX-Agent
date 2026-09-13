from typing import Any, Callable, Dict

from core.executor import SafeExecutor


class ToolRegistry:
    """
    سجل أدوات ALIX.

    مسؤول عن:
    - تسجيل الأدوات.
    - التحقق من وجود الأداة.
    - تنفيذ الأداة.
    - التعامل مع أخطاء التنفيذ.
    """

    def __init__(self, policy):
        self.policy = policy
        self.executor = SafeExecutor(policy=self.policy)
        self.tools: Dict[str, Callable] = {}

        self._register_tools()

    # ========================================================
    # REGISTER
    # ========================================================

    def register(
        self,
        name: str,
        function: Callable
    ):
        """
        تسجيل أداة جديدة.
        """

        if not isinstance(name, str):
            raise ValueError(
                "اسم الأداة يجب أن يكون نصًا."
            )

        name = name.strip()

        if not name:
            raise ValueError(
                "اسم الأداة فارغ."
            )

        if not callable(function):
            raise ValueError(
                f"الأداة غير قابلة للتنفيذ: {name}"
            )

        self.tools[name] = function

    # ========================================================
    # TOOL REGISTRATION
    # ========================================================

    def _register_tools(self):
        # SafeExecutor is the canonical execution authority.
        # list_files remains on FileSystemTools because SafeExecutor
        # does not currently expose an equivalent operation.
        from tools.filesystem import FileSystemTools

        filesystem = FileSystemTools(self.policy)

        self.register(
            "list_files",
            filesystem.list_files,
        )

        self.register(
            "read_file",
            self.executor.read_file,
        )

        self.register(
            "create_directory",
            self.executor.create_directory,
        )

        self.register(
            "write_file",
            self.executor.write_file,
        )

        self.register(
            "delete_file",
            self.executor.delete_file,
        )

        self.register(
            "run_python",
            self.executor.run_python,
        )

        self.register(
            "run_command",
            self.executor.run_command,
        )

        self.register(
            "system_info",
            self.executor.system_info,
        )

        self.register(
            "git_status",
            self.executor.git_read_only,
        )

    # ========================================================
    # QUERY
    # ========================================================

    def has(self, name: str) -> bool:

        return name in self.tools

    def names(self):

        return sorted(
            self.tools.keys()
        )

    # ========================================================
    # EXECUTE
    # ========================================================

    def execute(
        self,
        name: str,
        arguments: Dict[str, Any] | None = None,
    ):
        """
        Execute a registered tool through the Policy gate.

        Registry must never provide a bypass around Policy.
        User confirmation remains the responsibility of Agent.
        """

        # ---------------------------------------------------------
        # 1. Tool existence
        # ---------------------------------------------------------

        if not self.has(name):
            return {
                "ok": False,
                "error": f"الأداة غير موجودة: {name}",
            }

        # ---------------------------------------------------------
        # 2. Normalize arguments
        # ---------------------------------------------------------

        if arguments is None:
            arguments = {}

        if not isinstance(arguments, dict):
            return {
                "ok": False,
                "error": "arguments يجب أن تكون JSON object.",
            }

        # ---------------------------------------------------------
        # 3. Policy tool allowlist
        # ---------------------------------------------------------

        if not self.policy.tool_allowed(name):
            return {
                "ok": False,
                "error": (
                    f"الأداة مرفوضة بواسطة "
                    f"سياسة الأمان: {name}"
                ),
            }

        # ---------------------------------------------------------
        # 4. Policy argument validation
        # ---------------------------------------------------------

        try:
            valid = self.policy.validate_tool_arguments(
                name,
                arguments,
            )

        except AttributeError:
            return {
                "ok": False,
                "error": (
                    "Policy لا توفر "
                    "validate_tool_arguments()."
                ),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": (
                    f"فشل التحقق من arguments: {exc}"
                ),
            }

        if not valid:
            return {
                "ok": False,
                "error": (
                    "معطيات الأداة غير صالحة "
                    "أو مرفوضة بواسطة Policy."
                ),
            }

        # ---------------------------------------------------------
        # 5. Execute registered function
        # ---------------------------------------------------------

        try:
            # The canonical Policy/SafeExecutor contract uses
            # "script_path" directly. No legacy path translation.
            tool_arguments = dict(arguments)

            result = self.tools[name](
                **tool_arguments
            )

            if isinstance(result, dict):
                return result

            return {
                "ok": True,
                "result": result,
            }

        except TypeError as exc:
            return {
                "ok": False,
                "error": (
                    f"arguments غير صالحة "
                    f"للأداة {name}: {exc}"
                ),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }


from typing import Any, Callable, Dict


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

        from tools.filesystem import FileSystemTools
        from tools.system import SystemTools

        filesystem = FileSystemTools(
            self.policy
        )

        system = SystemTools(self.policy)

        self.register(
            "list_files",
            filesystem.list_files
        )

        self.register(
            "read_file",
            filesystem.read_file
        )

        self.register(
            "create_directory",
            filesystem.create_directory
        )

        self.register(
            "write_file",
            filesystem.write_file
        )

        self.register(
            "delete_file",
            filesystem.delete_file
        )

        self.register(
            "run_python",
            filesystem.run_python
        )

        self.register(
            "run_command",
            system.run_command
        )

        self.register(
            "system_info",
            system.system_info
        )

        self.register(
            "git_status",
            system.git_status
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
            tool_arguments = dict(arguments)

            # Registry compatibility:
            # Agent schema uses "script_path", while
            # FileSystemTools.run_python() expects "path".
            if name == "run_python":
                if "script_path" in tool_arguments:
                    if "path" in tool_arguments:
                        return {
                            "ok": False,
                            "error": (
                                "لا يمكن تحديد script_path وpath "
                                "معًا لأداة run_python."
                            ),
                        }

                    tool_arguments["path"] = tool_arguments.pop(
                        "script_path"
                    )

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


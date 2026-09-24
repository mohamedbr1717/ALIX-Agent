import time
from typing import Any, Callable, Dict

from core.executor import ExecutionResult, SafeExecutor
from core.feature_bridge import build_migrated_tool_handlers
from core.canary import find_canary


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

        # Migrated vertical slices are exposed through the single
        # core feature bridge. ToolRegistry does not know feature
        # implementation details.
        self._migrated_handlers = build_migrated_tool_handlers(
            self.policy
        )

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
        self.register(
            "list_files",
            self._migrated_handlers["list_files"],
        )

        # Migrated vertical slices are registered through the
        # core feature bridge.
        self.register(
            "read_file",
            self._migrated_handlers["read_file"],
        )

        self.register(
            "write_file",
            self._migrated_handlers["write_file"],
        )

        self.register(
            "delete_file",
            self._migrated_handlers["delete_file"],
        )

        self.register(
            "create_directory",
            self._migrated_handlers["create_directory"],
        )


        self.register(
            "run_python",
            self._migrated_handlers["run_python"],
        )

        self.register(
            "run_command",
            self._migrated_handlers["run_command"],
        )

        self.register(
            "system_info",
            self._migrated_handlers["system_info"],
        )

        self.register(
            "git_status",
            self._migrated_handlers["git_status"],
        )

        # Web tools: read-only, no API key. SSRF guard lives in tools/web.py.

        self.register(
            "web_search",
            self._migrated_handlers["web_search"],
        )

        self.register(
            "web_fetch",
            self._migrated_handlers["web_fetch"],
        )

        self.register(
            "search_files",
            self._migrated_handlers["search_files"],
        )

        self.register(
            "verify_file",
            self._migrated_handlers["verify_file"],
        )

        # remember_fact persists to the agent's memory store.
        self.register(
            "remember_fact",
            self._migrated_handlers["remember_fact"],
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
    # SCHEMA HELPER
    # ========================================================

    @staticmethod
    def _deny(name: str, started: float, message: str) -> dict:
        # SCHEMA FIX: every early-rejection path in execute() used to
        # return a bare {"ok": False, "error": ...} shape, different
        # from the canonical ExecutionResult contract every
        # SafeExecutor tool returns
        # (ok/action/message/stdout/stderr/returncode/evidence/duration).
        # A caller that only understands the canonical shape (as
        # Agent.execute_tool does) would see a malformed result for
        # exactly the security-relevant rejection paths (policy
        # denial, capability gate) -- the cases where a clear,
        # consistent shape matters most. Every path here now goes
        # through the same ExecutionResult.to_dict().
        return ExecutionResult(
            ok=False,
            action=name,
            message=message,
            duration=time.monotonic() - started,
        ).to_dict()

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

        started = time.monotonic()

        # ---------------------------------------------------------
        # 1. Tool existence
        # ---------------------------------------------------------

        if not self.has(name):
            return self._deny(
                name,
                started,
                f"الأداة غير موجودة: {name}",
            )

        # ---------------------------------------------------------
        # 2. Normalize arguments
        # ---------------------------------------------------------

        if arguments is None:
            arguments = {}

        if not isinstance(arguments, dict):
            return self._deny(
                name,
                started,
                "arguments يجب أن تكون JSON object.",
            )

        # ---------------------------------------------------------
        # 2b. Canary tripwire (fail-closed)
        # ---------------------------------------------------------
        # The honeytoken published in the system prompt is fake. If it
        # ever appears inside tool arguments, the model is acting on
        # injected content (or leaking the prompt) -> deny loudly.
        if find_canary(arguments) is not None:
            return self._deny(
                name,
                started,
                "CANARY TRIPWIRE: \u0631\u064f\u0635\u062f \u0631\u0645\u0632"
                " \u0643\u0634\u0641 \u0627\u0644\u062a\u0633\u0644\u0644"
                " \u062f\u0627\u062e\u0644 \u0648\u0633\u0627\u0626\u0637"
                " \u0627\u0644\u0623\u062f\u0627\u0629 \u2014 \u0645\u0631\u0641\u0648\u0636."
                " \u0647\u0630\u0627 \u064a\u0634\u064a\u0631"
                " \u0625\u0644\u0649 \u062d\u0642\u0646 \u062a\u0639\u0644\u064a\u0645\u0627\u062a.",
            )

        # ---------------------------------------------------------
        # 3. Policy tool allowlist
        # ---------------------------------------------------------

        if not self.policy.tool_allowed(name):
            return self._deny(
                name,
                started,
                f"الأداة مرفوضة بواسطة سياسة الأمان: {name}",
            )

        # ---------------------------------------------------------
        # 3b. Capability gate
        # ---------------------------------------------------------
        # SECURITY FIX: this check was missing entirely. Without it,
        # a disabled capability (e.g. capabilities["run_python"] =
        # False by default) had no effect when tools were dispatched
        # through ToolRegistry instead of Agent._execute_tool_body --
        # any code path that adopted this "cleaner" registry later
        # would have silently reopened the run_python bypass that was
        # fixed at the Policy layer. The gate must be enforced at
        # every dispatch entry point, not only in one of them.

        if not self.policy.capability_allowed(name):
            return self._deny(
                name,
                started,
                f"الأداة معطلة أمنيًا: {name}",
            )

        # ---------------------------------------------------------
        # 4. Policy argument validation
        # ---------------------------------------------------------

        try:
            valid = self.policy.validate_tool_arguments(
                name,
                arguments,
            )

        except AttributeError:
            return self._deny(
                name,
                started,
                "Policy لا توفر validate_tool_arguments().",
            )

        except Exception as exc:
            return self._deny(
                name,
                started,
                f"فشل التحقق من arguments: {exc}",
            )

        if not valid:
            return self._deny(
                name,
                started,
                "معطيات الأداة غير صالحة أو مرفوضة بواسطة Policy.",
            )

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

            # SCHEMA FIX: a non-dict return from a registered tool
            # (defensive path -- every current tool already returns
            # the canonical dict) is now wrapped in the same shape
            # instead of a bespoke {"ok": True, "result": ...}.
            return ExecutionResult(
                ok=True,
                action=name,
                message="",
                duration=time.monotonic() - started,
                evidence={"result": result},
            ).to_dict()

        except TypeError as exc:
            return self._deny(
                name,
                started,
                f"arguments غير صالحة للأداة {name}: {exc}",
            )

        except Exception as exc:
            return self._deny(name, started, str(exc))

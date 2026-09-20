#!/usr/bin/env python3

from __future__ import annotations

import gc
import importlib
import os
import re
import shutil
import time
import traceback
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


class Evaluation:
    def __init__(self):
        self.results = []
        self.root = Path(__file__).resolve().parent
        self.workspace = self.root / "workspace"
        self.probe_dir = self.workspace / ".alix-eval-v2"

        self.large_mb = max(
            8,
            int(os.environ.get("ALIX_EVAL_LARGE_MB", "32")),
        )

        self.registry = None
        self.executor = None
        self.policy = None

    def record(self, name, status, detail):
        self.results.append((name, status, detail))
        print(f"[{status:13}] {name}: {detail}")

    def load_runtime(self):
        policy_mod = importlib.import_module("core.policy")
        registry_mod = importlib.import_module("core.registry")
        executor_mod = importlib.import_module("core.executor")

        self.policy = policy_mod.Policy()
        self.registry = registry_mod.ToolRegistry(self.policy)

        self.executor = executor_mod.SafeExecutor(
            self.policy,
            command_timeout=30,
            python_timeout=30,
            max_output=4000,
        )

        self.probe_dir.mkdir(parents=True, exist_ok=True)

    def cleanup(self):
        if self.probe_dir.exists():
            shutil.rmtree(self.probe_dir, ignore_errors=True)

    @staticmethod
    def rss_kb():
        try:
            text = Path("/proc/self/status").read_text(
                encoding="utf-8",
                errors="replace",
            )

            match = re.search(
                r"^VmRSS:\s+(\d+)\s+kB$",
                text,
                re.MULTILINE,
            )

            return int(match.group(1)) if match else None

        except Exception:
            return None

    # ------------------------------------------------------------
    # 1. Registry dispatch
    # ------------------------------------------------------------

    def test_registry_dispatch(self):
        # Tools still served directly by bound methods.
        expected_bound = {
            "create_directory": "SafeExecutor.create_directory",
            "delete_file": "SafeExecutor.delete_file",
            "git_status": "SafeExecutor.git_read_only",
            "list_files": "FileSystemTools.list_files",
            "run_command": "SafeExecutor.run_command",
            "run_python": "SafeExecutor.run_python",
            "system_info": "SafeExecutor.system_info",
        }
        # Tools migrated to the Clean-Architecture vertical slice
        # (features/file_access), registered via the feature bridge.
        # These are plain functions, not bound methods.
        expected_migrated = {"read_file", "write_file"}

        def describe(fn):
            owner = getattr(fn, "__self__", None)
            if owner is None:
                return f"function:{getattr(fn, '__name__', '?')}"
            return f"{owner.__class__.__name__}.{fn.__name__}"

        actual = {
            name: describe(fn)
            for name, fn in self.registry.tools.items()
        }

        expected_names = set(expected_bound) | expected_migrated
        missing = sorted(expected_names - set(actual))

        wrong = {
            name: (expected_bound[name], actual.get(name))
            for name in expected_bound
            if actual.get(name) != expected_bound[name]
        }
        for name in expected_migrated:
            handler = self.registry.tools.get(name)
            bridge = self.registry._migrated_handlers.get(name)
            if handler is not bridge:
                wrong[name] = ("migrated slice handler", describe(handler))

        if missing or wrong:
            self.record(
                "registry dispatch integrity",
                FAIL,
                f"missing={missing!r}, wrong={wrong!r}",
            )
        else:
            self.record(
                "registry dispatch integrity",
                PASS,
                "all expected tools resolve to the current implementation",
            )

    # ------------------------------------------------------------
    # 2. Real command execution
    # ------------------------------------------------------------

    def test_command_execution(self):
        result = self.registry.execute(
            "run_command",
            {"command": "printf ALIX_V2_COMMAND_OK"},
        )

        returncode = result.get(
            "returncode",
            result.get("exit_code"),
        )

        if (
            result.get("ok") is True
            and result.get("stdout") == "ALIX_V2_COMMAND_OK"
            and returncode == 0
        ):
            self.record(
                "real command execution",
                PASS,
                "Registry -> Policy -> SafeExecutor executed a real command",
            )
        else:
            self.record(
                "real command execution",
                FAIL,
                f"result={result!r}",
            )

    # ------------------------------------------------------------
    # 3. Shell injection
    # ------------------------------------------------------------

    def test_command_injection(self):
        marker = self.probe_dir / "injection_marker"

        payloads = [
            f"printf ALIX_OK; touch {marker}",
            f"printf ALIX_OK && touch {marker}",
            f"printf ALIX_OK | touch {marker}",
            f"printf ALIX_OK > {marker}",
            f"printf ALIX_OK $(touch {marker})",
        ]

        failures = []

        for payload in payloads:
            if marker.exists():
                marker.unlink()

            result = self.registry.execute(
                "run_command",
                {"command": payload},
            )

            if marker.exists():
                failures.append(
                    f"side effect executed: {payload!r}; "
                    f"result={result!r}"
                )

        if failures:
            self.record(
                "shell injection containment",
                FAIL,
                "; ".join(failures),
            )
        else:
            self.record(
                "shell injection containment",
                PASS,
                f"{len(payloads)} injection payloads caused no marker creation",
            )

    # ------------------------------------------------------------
    # 4. Path containment
    # ------------------------------------------------------------

    def test_path_containment(self):
        cases = [
            (
                "read_file",
                {"path": "../outside.txt"},
            ),
            (
                "read_file",
                {"path": str(self.root.parent / "outside.txt")},
            ),
            (
                "write_file",
                {
                    "path": "../outside.txt",
                    "content": "NO",
                },
            ),
            (
                "delete_file",
                {"path": "../outside.txt"},
            ),
        ]

        failures = []

        for tool, args in cases:
            result = self.registry.execute(tool, args)

            if result.get("ok") is True:
                failures.append(
                    f"{tool} accepted {args!r}: {result!r}"
                )

        if failures:
            self.record(
                "workspace path containment",
                FAIL,
                "; ".join(failures),
            )
        else:
            self.record(
                "workspace path containment",
                PASS,
                "workspace escape attempts were denied",
            )

    # ------------------------------------------------------------
    # 5. run_python must fail closed through Registry
    # ------------------------------------------------------------

    def test_run_python_fail_closed(self):
        script = self.probe_dir / "registry_python_probe.py"

        script.write_text(
            "from pathlib import Path\n"
            "Path('RUN_PYTHON_MUST_NOT_RUN').write_text('executed')\n",
            encoding="utf-8",
        )

        result = self.registry.execute(
            "run_python",
            {
                "script_path": str(
                    script.relative_to(self.workspace)
                )
            },
        )

        marker = self.workspace / "RUN_PYTHON_MUST_NOT_RUN"

        capability_disabled = (
            self.policy.capability_allowed("run_python") is False
        )

        # SCHEMA_CONTRACT.md: the denial reason lives in "message";
        # "error" is not a contract field (kept below as fallback only).
        denied = (
            result.get("ok") is False
            and (
                "معطلة" in str(result.get("message", ""))
                or "disabled" in str(result.get("message", "")).lower()
                or "معطلة" in str(result.get("error", ""))
                or "disabled" in str(result.get("error", "")).lower()
            )
        )

        if (
            capability_disabled
            and denied
            and not marker.exists()
        ):
            self.record(
                "run_python registry fail-closed",
                PASS,
                "run_python is disabled and no Python side effect occurred",
            )
        else:
            self.record(
                "run_python registry fail-closed",
                FAIL,
                (
                    f"capability={capability_disabled}, "
                    f"denied={denied}, "
                    f"marker={marker.exists()}, "
                    f"result={result!r}"
                ),
            )

    # ------------------------------------------------------------
    # 6. Direct SafeExecutor Python sandbox
    # ------------------------------------------------------------

    def test_direct_python_sandbox(self):
        script = self.probe_dir / "sandbox_probe.py"
        inside = self.probe_dir / "sandbox_inside_marker"
        outside = Path("/tmp/ALIX_V2_OUTSIDE_MARKER")

        if outside.exists():
            try:
                outside.unlink()
            except OSError:
                pass

        script.write_text(
            "from pathlib import Path\n"
            "Path('/workspace/.alix-eval-v2/sandbox_inside_marker').write_text('inside-ok')\n"
            f"Path({str(outside)!r}).write_text('outside')\n",
            encoding="utf-8",
        )

        result = self.executor.run_python(
            str(script.relative_to(self.workspace))
        )

        if result.get("ok") is True:
            inside_ok = inside.exists()
            outside_ok = outside.exists()

            if inside_ok and not outside_ok:
                self.record(
                    "direct Python sandbox",
                    PASS,
                    "workspace side effect succeeded while outside marker was blocked",
                )
            else:
                self.record(
                    "direct Python sandbox",
                    FAIL,
                    (
                        f"inside_marker={inside_ok}, "
                        f"outside_marker={outside_ok}, "
                        f"result={result!r}"
                    ),
                )

        else:
            message = str(result.get("message", ""))

            if (
                "العزل الحقيقي غير متاح" in message
                or "sandbox" in message.lower()
            ):
                self.record(
                    "direct Python sandbox",
                    PASS,
                    "execution failed closed because real sandbox was unavailable",
                )
            else:
                self.record(
                    "direct Python sandbox",
                    FAIL,
                    f"unexpected failure: {result!r}",
                )

        if outside.exists():
            try:
                outside.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------
    # 7. read_file contract
    # ------------------------------------------------------------

    def test_read_contract(self):
        probe = self.probe_dir / "read_contract.txt"

        probe.write_text(
            "ALIX_LINE_1\n"
            "ALIX_LINE_2\n"
            "ALIX_LINE_3\n",
            encoding="utf-8",
        )

        result = self.registry.execute(
            "read_file",
            {
                "path": str(
                    probe.relative_to(self.workspace)
                ),
                "start_line": 2,
                "end_line": 2,
            },
        )

        evidence = result.get("evidence") or {}

        if (
            result.get("ok") is True
            and result.get("stdout") == "ALIX_LINE_2"
            and evidence.get("returned_lines") == 1
            and evidence.get("line_count") == 3
        ):
            self.record(
                "read_file real contract",
                PASS,
                "line-range contract verified",
            )
        else:
            self.record(
                "read_file real contract",
                FAIL,
                f"result={result!r}",
            )

    # ------------------------------------------------------------
    # 8. Large-file memory behavior
    # ------------------------------------------------------------

    def test_large_read_behavior(self):
        target = self.probe_dir / "large_read_probe.bin"
        size = self.large_mb * 1024 * 1024

        with target.open("wb") as fh:
            fh.write(b"A" * size)

        gc.collect()
        rss_before = self.rss_kb()

        result = self.registry.execute(
            "read_file",
            {
                "path": str(
                    target.relative_to(self.workspace)
                )
            },
        )

        gc.collect()
        rss_after = self.rss_kb()

        evidence = result.get("evidence") or {}

        rss_delta = None
        if rss_before is not None and rss_after is not None:
            rss_delta = max(0, rss_after - rss_before)

        valid = (
            result.get("ok") is True
            and evidence.get("exists") is True
            and evidence.get("is_file") is True
            and evidence.get("size_bytes") == size
            and evidence.get("streamed") is True
            and evidence.get("output_truncated") is True
        )

        if valid:
            self.record(
                "large-file read resource behavior",
                PASS,
                (
                    f"size={size} bytes, "
                    f"streamed=True, "
                    f"output_truncated=True, "
                    f"RSS_delta_kB={rss_delta}"
                ),
            )
        else:
            self.record(
                "large-file read resource behavior",
                FAIL,
                (
                    f"result={result!r}, "
                    f"RSS_delta_kB={rss_delta}"
                ),
            )


    # ------------------------------------------------------------
    # 9. Output bound
    # ------------------------------------------------------------

    def test_output_bound(self):
        command = "printf " + ("X" * 200000)

        if not self.policy.command_allowed(command):
            self.record(
                "command output bound",
                INCONCLUSIVE,
                "Policy denied the large-output probe; Policy was not weakened",
            )
            return

        result = self.registry.execute(
            "run_command",
            {"command": command},
        )

        stdout = result.get("stdout", "")
        evidence = result.get("evidence") or {}

        if (
            len(stdout) <= self.executor.max_output
            and evidence.get("bounded_output") is True
        ):
            self.record(
                "command output bound",
                PASS,
                (
                    f"stdout={len(stdout)} chars, "
                    f"max_output={self.executor.max_output}"
                ),
            )
        else:
            self.record(
                "command output bound",
                FAIL,
                f"stdout_len={len(stdout)}, evidence={evidence!r}",
            )

    # ------------------------------------------------------------
    # 10. Timeout
    # ------------------------------------------------------------

    def test_timeout(self):
        candidates = [
            "sleep 2",
            'python3 -c "import time; time.sleep(2)"',
            'python -c "import time; time.sleep(2)"',
            "yes",
        ]

        allowed = [
            command
            for command in candidates
            if self.policy.command_allowed(command)
        ]

        if not allowed:
            self.record(
                "real command timeout",
                INCONCLUSIVE,
                (
                    "no existing Policy-allowed long-running command; "
                    "Policy was not weakened"
                ),
            )
            return

        command = allowed[0]

        started = time.monotonic()

        result = self.registry.execute(
            "run_command",
            {"command": command},
        )

        elapsed = time.monotonic() - started

        evidence = result.get("evidence") or {}

        timed_out = bool(
            evidence.get("timed_out")
            or "مهلة" in str(result.get("message", ""))
        )

        if (
            timed_out
            and elapsed < self.executor.command_timeout + 3
        ):
            self.record(
                "real command timeout",
                PASS,
                f"command={command!r}, elapsed={elapsed:.2f}s",
            )
        else:
            self.record(
                "real command timeout",
                FAIL,
                (
                    f"command={command!r}, "
                    f"elapsed={elapsed:.2f}s, "
                    f"result={result!r}"
                ),
            )

    # ------------------------------------------------------------
    # 11. Policy denial invariants
    # ------------------------------------------------------------

    def test_dangerous_command_denial(self):
        dangerous = [
            "rm -rf /",
            "rm -rf .",
            "shutdown",
            "reboot",
            "mkfs",
            "dd if=/dev/zero of=/dev/null",
        ]

        violations = []

        for command in dangerous:
            if self.policy.command_allowed(command) is not False:
                violations.append(command)

        if not violations:
            self.record(
                "dangerous command denial",
                PASS,
                f"denied={len(dangerous)}/{len(dangerous)} dangerous commands",
            )
        else:
            self.record(
                "dangerous command denial",
                FAIL,
                f"Policy allowed dangerous commands: {violations!r}",
            )

    def test_malformed_command_denial(self):
        malformed = [
            "",
            "   ",
            "python -c",
            "python3 -c",
            "echo 'unterminated",
        ]

        violations = []

        for command in malformed:
            if self.policy.command_allowed(command) is not False:
                violations.append(command)

        if not violations:
            self.record(
                "malformed command denial",
                PASS,
                f"denied={len(malformed)}/{len(malformed)} malformed commands",
            )
        else:
            self.record(
                "malformed command denial",
                FAIL,
                f"Policy allowed malformed commands: {violations!r}",
            )

    # ------------------------------------------------------------
    # 13. Recovery
    # ------------------------------------------------------------

    def test_recovery(self):
        result = self.registry.execute(
            "run_command",
            {"command": "printf ALIX_V2_RECOVERY_OK"},
        )

        if (
            result.get("ok") is True
            and result.get("stdout") == "ALIX_V2_RECOVERY_OK"
        ):
            self.record(
                "post-failure recovery",
                PASS,
                "executor remained usable after previous probes",
            )
        else:
            self.record(
                "post-failure recovery",
                FAIL,
                f"result={result!r}",
            )

    # ------------------------------------------------------------
    # 12. Write/Delete
    # ------------------------------------------------------------

    def test_write_delete(self):
        target = self.probe_dir / "mutation_probe.txt"

        write = self.registry.execute(
            "write_file",
            {
                "path": str(
                    target.relative_to(self.workspace)
                ),
                "content": "ALIX_WRITE_V2",
            },
        )

        if not (
            write.get("ok") is True
            and target.exists()
        ):
            self.record(
                "write/delete real contract",
                FAIL,
                f"write failed: {write!r}",
            )
            return

        delete = self.registry.execute(
            "delete_file",
            {
                "path": str(
                    target.relative_to(self.workspace)
                )
            },
        )

        backup = target.with_name(
            target.name + ".alix-delete-backup"
        )

        if (
            delete.get("ok") is True
            and not target.exists()
            and backup.exists()
        ):
            self.record(
                "write/delete real contract",
                PASS,
                "write/delete verification and backup observed",
            )
        else:
            self.record(
                "write/delete real contract",
                FAIL,
                (
                    f"delete={delete!r}, "
                    f"target={target.exists()}, "
                    f"backup={backup.exists()}"
                ),
            )

    # ------------------------------------------------------------
    # 13. Git
    # ------------------------------------------------------------

    def test_git_read_only(self):
        result = self.registry.execute(
            "git_status",
            {"action": "status"},
        )

        if result.get("ok") is True:
            evidence = result.get("evidence") or {}

            if (
                evidence.get("read_only") is True
                and evidence.get("bounded_output") is True
            ):
                self.record(
                    "git read-only bounded execution",
                    PASS,
                    "git status used bounded read-only execution",
                )
            else:
                self.record(
                    "git read-only bounded execution",
                    FAIL,
                    f"unexpected evidence={evidence!r}",
                )
        else:
            self.record(
                "git read-only bounded execution",
                FAIL,
                f"result={result!r}",
            )

    # ------------------------------------------------------------
    # 14. system_info
    # ------------------------------------------------------------

    def test_system_info(self):
        result = self.registry.execute(
            "system_info",
            {},
        )

        if result.get("ok") is True:
            self.record(
                "system_info real execution",
                PASS,
                "system_info completed successfully",
            )
        else:
            self.record(
                "system_info real execution",
                FAIL,
                f"result={result!r}",
            )

    # ------------------------------------------------------------
    # Main
    # ------------------------------------------------------------

    def run(self):
        print("=" * 72)
        print("ALIX REAL EXECUTION EVALUATION V2")
        print("=" * 72)
        print(f"repo      : {self.root}")
        print(f"workspace : {self.workspace}")
        print(f"large file: {self.large_mb} MiB")
        print()

        try:
            self.load_runtime()
        except Exception:
            print("[FATAL] runtime initialization failed")
            traceback.print_exc()
            return 2

        tests = [
            self.test_registry_dispatch,
            self.test_command_execution,
            self.test_command_injection,
            self.test_path_containment,
            self.test_run_python_fail_closed,
            self.test_direct_python_sandbox,
            self.test_read_contract,
            self.test_large_read_behavior,
            self.test_output_bound,
            self.test_timeout,
            self.test_dangerous_command_denial,
            self.test_malformed_command_denial,
            self.test_recovery,
            self.test_write_delete,
            self.test_git_read_only,
            self.test_system_info,
        ]

        try:
            for test in tests:
                try:
                    test()
                except Exception as exc:
                    self.record(
                        test.__name__,
                        FAIL,
                        f"unhandled exception: {exc!r}",
                    )
                    traceback.print_exc()
        finally:
            self.cleanup()

        counts = {
            PASS: sum(
                status == PASS
                for _, status, _ in self.results
            ),
            FAIL: sum(
                status == FAIL
                for _, status, _ in self.results
            ),
            INCONCLUSIVE: sum(
                status == INCONCLUSIVE
                for _, status, _ in self.results
            ),
        }

        print()
        print("=" * 72)
        print("ALIX REAL EXECUTION EVALUATION V2 — SUMMARY")
        print("=" * 72)
        print(f"PASS         : {counts[PASS]}")
        print(f"FAIL         : {counts[FAIL]}")
        print(f"INCONCLUSIVE : {counts[INCONCLUSIVE]}")
        print(f"TOTAL        : {len(self.results)}")
        print()

        if counts[FAIL]:
            print(
                "RESULT: FAIL — real guarantees require investigation."
            )
            return 1

        if counts[INCONCLUSIVE]:
            print(
                "RESULT: INCONCLUSIVE — some guarantees could not "
                "be exercised under the current Policy."
            )
            return 3

        print(
            "RESULT: PASS — all exercised real guarantees passed."
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(Evaluation().run())

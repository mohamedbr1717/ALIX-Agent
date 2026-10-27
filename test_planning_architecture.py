"""Decision 1 — planning-specific architecture rules (spec §7).

Beyond the project's general boundary test, Decision 1 adds:
- features/planning imports NOTHING from core, and only stdlib,
  domain.* and itself from anywhere;
- no module outside core/feature_bridge.py imports
  features.planning (the bridge stays the only core->features
  gateway);
- the slice holds no dispatch machinery of its own: no
  SafeExecutor / ToolRegistry / _execute_tool_body /
  build_migrated_tool_handlers / confirm_tool references — the
  injected ToolDispatchPort is the only execution entrance;
- the tool registry stays in sync by hand, as the project
  requires: prompts.TOOLS carries plan_status/plan_cancel and
  Policy's tool_permissions levels match the spec (read/write).
"""
import ast
import sys
import unittest
from pathlib import Path

SLICE_ROOT = Path("features/planning")
_STDLIB = set(sys.stdlib_module_names)

FORBIDDEN_DISPATCH_IDENTIFIERS = {
    "SafeExecutor",
    "ToolRegistry",
    "_execute_tool_body",
    "build_migrated_tool_handlers",
    "confirm_tool",
}


def imported_modules(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                modules.append(node.module)
    return modules


def all_identifiers(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name)
    return names


class TestSliceImports(unittest.TestCase):
    def _slice_files(self):
        return sorted(SLICE_ROOT.rglob("*.py"))

    def test_slice_imports_nothing_from_core(self):
        violations = []
        for py_file in self._slice_files():
            for mod in imported_modules(py_file):
                if mod == "core" or mod.startswith("core."):
                    violations.append(f"{py_file}: {mod}")
        self.assertEqual(violations, [])

    def test_slice_imports_only_stdlib_domain_and_itself(self):
        violations = []
        for py_file in self._slice_files():
            for mod in imported_modules(py_file):
                top = mod.split(".")[0]
                if top in _STDLIB:
                    continue
                if mod == "domain" or mod.startswith("domain."):
                    continue
                if mod == "features.planning" or mod.startswith(
                    "features.planning."
                ):
                    continue
                violations.append(f"{py_file}: {mod}")
        self.assertEqual(violations, [])

    def test_no_dispatch_machinery_inside_the_slice(self):
        violations = []
        for py_file in self._slice_files():
            found = (
                all_identifiers(py_file)
                & FORBIDDEN_DISPATCH_IDENTIFIERS
            )
            if found:
                violations.append(
                    f"{py_file}: {sorted(found)}"
                )
        self.assertEqual(violations, [])


class TestOnlyTheBridgeKnowsTheSlice(unittest.TestCase):
    def _scan(self, roots, exclude):
        violations = []
        for root in roots:
            for py_file in sorted(root.rglob("*.py")):
                if str(py_file) in exclude:
                    continue
                if "__pycache__" in py_file.parts:
                    continue
                for mod in imported_modules(py_file):
                    if mod == "features.planning" or (
                        mod.startswith("features.planning.")
                    ):
                        violations.append(
                            f"{py_file}: {mod}"
                        )
        return violations

    def test_core_outside_the_bridge(self):
        violations = self._scan(
            [Path("core")], {"core/feature_bridge.py"}
        )
        self.assertEqual(violations, [])

    def test_domain_and_other_features(self):
        roots = [Path("domain")]
        features = Path("features")
        if features.is_dir():
            roots.extend(
                d
                for d in features.iterdir()
                if d.is_dir() and d.name != "planning"
            )
        violations = self._scan(roots, set())
        self.assertEqual(violations, [])

    def test_root_level_files(self):
        violations = []
        for py_file in sorted(Path(".").glob("*.py")):
            if py_file.name.startswith("test_"):
                continue
            for mod in imported_modules(py_file):
                if mod == "features.planning" or mod.startswith(
                    "features.planning."
                ):
                    violations.append(f"{py_file}: {mod}")
        self.assertEqual(violations, [])


def _tools_names():
    tree = ast.parse(
        Path("core/agent/prompts.py").read_text(
            encoding="utf-8"
        )
    )
    names = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TOOLS"
                for t in node.targets
            )
        ):
            for elt in node.value.elts:
                for sub in ast.walk(elt):
                    if isinstance(sub, ast.Dict):
                        for key, value in zip(
                            sub.keys, sub.values
                        ):
                            if (
                                isinstance(key, ast.Constant)
                                and key.value == "name"
                                and isinstance(
                                    value, ast.Constant
                                )
                            ):
                                names.append(value.value)
    return names


def _tool_permissions():
    tree = ast.parse(
        Path("core/policy/_config.py").read_text(
            encoding="utf-8"
        )
    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {
            k.value: v.value
            for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant)
            and isinstance(v, ast.Constant)
        }
        # The permissions dict maps tool names to LEVEL strings;
        # the argument-schema dict (same file) maps them to
        # dicts and is excluded by the value-type check above.
        if pairs.get("plan_status") in (
            "read",
            "write",
            "execute",
            "destructive",
        ) and "calendar_delete" in pairs:
            return pairs
    return {}


class TestRegistrySync(unittest.TestCase):
    def test_prompts_carry_the_two_plan_tools(self):
        names = _tools_names()
        self.assertIn("plan_status", names)
        self.assertIn("plan_cancel", names)

    def test_policy_levels_match_the_spec(self):
        permissions = _tool_permissions()
        self.assertEqual(permissions.get("plan_status"), "read")
        self.assertEqual(permissions.get("plan_cancel"), "write")


if __name__ == "__main__":
    unittest.main()

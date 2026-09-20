"""
تدقيق اعتمادية آلي حقيقي (لا مراجعة بصرية): يفحص أشجار ast الفعلية
لكل ملف تحت features/ للتأكد أن الاعتمادية تتجه للداخل فقط كما
تفرضه Clean/Hexagonal Architecture:

    domain        -> لا يعتمد على شيء داخلي
    application   -> يعتمد على domain فقط
    infrastructure-> يعتمد على domain + application (لتنفيذ الـ ports)
    interfaces    -> يعتمد على domain + application

composition.py (جذر التركيب) مستثنى عمدًا -- هو المكان الوحيد
المسموح له بمعرفة كل الطبقات معًا وربطها.

كما يتحقق أن core/*.py القديم لا يستورد من features/ إطلاقًا حتى
يصبح الربط قرارًا صريحًا لاحقًا، لا تسربًا غير مقصود.
"""

import ast
import unittest
from pathlib import Path

LAYER_RULES = {
    "domain": set(),
    "application": {"domain"},
    "infrastructure": {"domain", "application"},
    "interfaces": {"domain", "application"},
}

FEATURE_ROOT = Path("features")
CORE_ROOT = Path("core")


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)

    return modules


class TestArchitectureBoundaries(unittest.TestCase):

    def test_layer_dependencies_point_inward_only(self):
        violations = []

        if not FEATURE_ROOT.is_dir():
            self.skipTest("لا يوجد مجلد features/ بعد.")

        for feature_dir in sorted(FEATURE_ROOT.iterdir()):
            if not feature_dir.is_dir():
                continue

            for layer, allowed_internal in LAYER_RULES.items():
                layer_dir = feature_dir / layer

                if not layer_dir.is_dir():
                    continue

                for py_file in layer_dir.rglob("*.py"):
                    if (
                        py_file.name == "__init__.py"
                        and py_file.stat().st_size == 0
                    ):
                        continue

                    for mod in imported_modules(py_file):
                        prefix = f"features.{feature_dir.name}."

                        if not mod.startswith(prefix):
                            continue

                        parts = mod.split(".")
                        if len(parts) < 3:
                            continue

                        target_layer = parts[2]

                        if target_layer == layer:
                            continue

                        if target_layer not in allowed_internal:
                            violations.append(
                                f"{py_file}: يستورد '{mod}' "
                                f"(طبقة {target_layer})، غير مسموح "
                                f"لطبقة {layer} "
                                f"(المسموح: {allowed_internal or 'لا شيء'})"
                            )

        self.assertEqual(
            violations,
            [],
            "انتهاكات اتجاه الاعتمادية:\n" + "\n".join(violations),
        )

    def test_core_never_imports_from_features(self):
        violations = []

        if not CORE_ROOT.is_dir():
            self.skipTest("لا يوجد مجلد core/.")

        for py_file in CORE_ROOT.rglob("*.py"):
            for mod in imported_modules(py_file):
                if mod == "features" or mod.startswith("features."):
                    violations.append(f"{py_file}: يستورد '{mod}'")

        self.assertEqual(
            violations,
            [],
            "core/ يستورد من features/ رغم عدم اتخاذ قرار الربط بعد:\n"
            + "\n".join(violations),
        )

    def test_root_level_files_never_import_from_features(self):
        violations = []

        for py_file in Path(".").glob("*.py"):
            if py_file.name.startswith("test_"):
                continue

            try:
                for mod in imported_modules(py_file):
                    if mod == "features" or mod.startswith("features."):
                        violations.append(f"{py_file}: يستورد '{mod}'")
            except SyntaxError:
                continue

        self.assertEqual(
            violations,
            [],
            "ملف جذري يستورد من features/ رغم عدم اتخاذ قرار الربط بعد:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()

"""Behavioral tests for the list_files vertical slice."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.feature_bridge import build_migrated_tool_handlers
from core.policy import Policy
from features.file_access.application.dto.list_files import (
    ListFilesRequest,
)
from features.file_access.application.use_cases.list_files import (
    ListFilesUseCase,
)
from features.file_access.composition import build_list_files_controller
from features.file_access.infrastructure.adapters.policy_file_listing_authorization import (
    PolicyFileListingAuthorizationAdapter,
)


def make_policy(tmp: str) -> Policy:
    policy = Policy()
    policy.workspace = Path(tmp).resolve()
    return policy


def seed(tmp: str) -> None:
    base = Path(tmp)
    (base / "adir").mkdir()
    (base / "b.txt").write_text("hello")
    (base / ".hidden").write_text("x")


class TestListFilesFeature(unittest.TestCase):
    def test_controller_wires_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed(tmp)
            controller = build_list_files_controller(make_policy(tmp))
            result = controller.handle({"path": "."})
            self.assertTrue(result["ok"], result.get("message"))
            self.assertEqual(result["action"], "list_files")
            evidence = result["evidence"]
            names = [i["name"] for i in evidence["items"]]
            self.assertIn("adir", names)
            self.assertIn("b.txt", names)
            self.assertEqual(evidence["count"], len(evidence["items"]))
            by_name = {i["name"]: i for i in evidence["items"]}
            self.assertEqual(by_name["adir"]["type"], "directory")
            self.assertEqual(by_name["b.txt"]["type"], "file")
            self.assertEqual(by_name["b.txt"]["size"], 5)

    def test_directories_sort_before_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed(tmp)  # adir (dir) vs b.txt (file)
            controller = build_list_files_controller(make_policy(tmp))
            result = controller.handle({"path": "."})
            names = [i["name"] for i in result["evidence"]["items"]]
            self.assertLess(names.index("adir"), names.index("b.txt"))

    def test_dotfiles_hidden_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed(tmp)
            controller = build_list_files_controller(make_policy(tmp))
            result = controller.handle({"path": "."})
            names = [i["name"] for i in result["evidence"]["items"]]
            self.assertNotIn(".hidden", names)

    def test_all_true_shows_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed(tmp)
            controller = build_list_files_controller(make_policy(tmp))
            result = controller.handle({"path": ".", "all": True})
            names = [i["name"] for i in result["evidence"]["items"]]
            self.assertIn(".hidden", names)

    def test_sensitive_filenames_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            # Fixture sanity: credentials.json must really be sensitive
            # under this policy, or the test is vacuous.
            self.assertTrue(
                policy.is_sensitive_path(Path(tmp) / "credentials.json")
            )
            (Path(tmp) / "credentials.json").write_text("{}")
            (Path(tmp) / "notes.txt").write_text("x")
            controller = build_list_files_controller(policy)
            result = controller.handle({"path": ".", "all": True})
            names = [i["name"] for i in result["evidence"]["items"]]
            self.assertNotIn("credentials.json", names)
            self.assertIn("notes.txt", names)

    def test_workspace_escape_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_list_files_controller(make_policy(tmp))
            result = controller.handle({"path": "../outside"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "list_files")

    def test_nonexistent_path_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = build_list_files_controller(make_policy(tmp))
            result = controller.handle({"path": "no-such-dir"})
            self.assertFalse(result["ok"])

    def test_file_path_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed(tmp)
            controller = build_list_files_controller(make_policy(tmp))
            result = controller.handle({"path": "b.txt"})
            self.assertFalse(result["ok"])

    def test_use_case_denies_before_runner_is_touched(self):
        class ExplodingRunner:
            def run_list_files(self, path, all):
                raise AssertionError("runner must not be called")

        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(tmp)
            use_case = ListFilesUseCase(
                authorization=PolicyFileListingAuthorizationAdapter(policy),
                runner=ExplodingRunner(),
            )
            result = use_case.execute(ListFilesRequest(path="../outside"))
            self.assertFalse(result["ok"])

    def test_registry_handler_goes_through_new_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed(tmp)
            policy = make_policy(tmp)
            handlers = build_migrated_tool_handlers(policy)
            self.assertIn("list_files", handlers)
            result = handlers["list_files"](path=".")
            self.assertTrue(result["ok"], result.get("message"))
            names = [i["name"] for i in result["evidence"]["items"]]
            self.assertIn("b.txt", names)


if __name__ == "__main__":
    unittest.main()

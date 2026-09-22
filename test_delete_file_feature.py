"""Behavioral tests for the delete_file vertical slice migration.

delete_file is a destructive tool: the migrated slice must preserve the
live SafeExecutor behavior exactly -- validate_file_path gate,
.alix-delete-backup before unlink, post-delete verification, and the
evidence shape (path, deleted, backup, rollback_available).
"""
import tempfile
import unittest
from pathlib import Path

from core.policy import Policy
from features.file_access.application.dto.delete_file import DeleteFileRequest
from features.file_access.application.use_cases.delete_file import (
    DeleteFileUseCase,
)
from features.file_access.composition import build_delete_file_controller
from features.file_access.infrastructure.adapters.policy_authorization import (
    PolicyAuthorizationAdapter,
)
from features.file_access.infrastructure.adapters.workspace_file_storage import (
    WorkspaceFileStorageAdapter,
)


class DeleteFileSliceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)

        self.policy = Policy()
        self.policy.workspace = self.workspace

        self.storage = WorkspaceFileStorageAdapter(self.policy)
        self.authorization = PolicyAuthorizationAdapter(self.policy)
        self.use_case = DeleteFileUseCase(
            storage=self.storage,
            authorization=self.authorization,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, content="data"):
        p = self.workspace / name
        p.write_text(content, encoding="utf-8")
        return p


class TestDeleteFileUseCase(DeleteFileSliceTestBase):
    def test_deletes_real_file_with_backup_and_verification(self):
        target = self._write("notes.txt", "hello")
        result = self.use_case.execute(DeleteFileRequest(path="notes.txt"))

        self.assertTrue(result["ok"])
        self.assertFalse(target.exists())

        backup = self.workspace / "notes.txt.alix-delete-backup"
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "hello")

        self.assertTrue(result["evidence"]["deleted"])
        self.assertTrue(result["evidence"]["rollback_available"])
        self.assertIn("backup", result["evidence"])

    def test_refuses_sensitive_path(self):
        self._write(".env", "SECRET=1")
        result = self.use_case.execute(DeleteFileRequest(path=".env"))

        self.assertFalse(result["ok"])
        # The sensitive file must survive the refusal.
        self.assertTrue((self.workspace / ".env").exists())

    def test_refuses_path_outside_workspace(self):
        result = self.use_case.execute(DeleteFileRequest(path="../outside.txt"))
        self.assertFalse(result["ok"])

    def test_refuses_missing_file(self):
        result = self.use_case.execute(DeleteFileRequest(path="ghost.txt"))
        self.assertFalse(result["ok"])
        self.assertIn("غير موجود", result["message"])

    def test_refuses_directory(self):
        (self.workspace / "subdir").mkdir()
        result = self.use_case.execute(DeleteFileRequest(path="subdir"))
        self.assertFalse(result["ok"])

    def test_refuses_blank_path(self):
        result = self.use_case.execute(DeleteFileRequest(path="   "))
        self.assertFalse(result["ok"])

    def test_authorization_checked_before_storage_is_touched(self):
        class ExplodingStorage:
            def delete_file(self, path):
                raise AssertionError(
                    "storage must not be touched when unauthorized"
                )

        use_case = DeleteFileUseCase(
            storage=ExplodingStorage(),
            authorization=self.authorization,
        )
        result = use_case.execute(DeleteFileRequest(path=".env"))
        self.assertFalse(result["ok"])

    def test_denial_envelope_matches_schema_contract(self):
        result = self.use_case.execute(DeleteFileRequest(path="   "))
        for key in (
            "ok", "action", "message", "stdout", "stderr",
            "returncode", "evidence", "duration",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["action"], "delete_file")


class TestDeleteFileWiring(unittest.TestCase):
    def test_bridge_exposes_delete_file(self):
        from core.feature_bridge import build_migrated_tool_handlers

        handlers = build_migrated_tool_handlers(Policy())
        self.assertIn("delete_file", handlers)

    def test_controller_end_to_end(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            ws = Path(tmp.name)
            policy = Policy()
            policy.workspace = ws
            (ws / "t.txt").write_text("x", encoding="utf-8")

            controller = build_delete_file_controller(policy)
            result = controller.handle({"path": "t.txt"})

            self.assertTrue(result["ok"])
            self.assertFalse((ws / "t.txt").exists())
            self.assertTrue((ws / "t.txt.alix-delete-backup").exists())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()

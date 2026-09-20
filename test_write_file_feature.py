import tempfile
import unittest
from pathlib import Path

from core.policy import Policy
from features.file_access.application.dto.write_file import (
    WriteFileRequest,
)
from features.file_access.application.use_cases.write_file import (
    WriteFileUseCase,
)
from features.file_access.infrastructure.adapters.workspace_file_storage import (
    WorkspaceFileStorageAdapter,
)


class TestWriteFileFeature(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)

        self.policy = Policy()
        self.policy.workspace = self.workspace

        self.storage = WorkspaceFileStorageAdapter(
            policy=self.policy,
        )

        class AllowingAuthorization:
            def can_write_file(self, path):
                return True

        self.authorization = AllowingAuthorization()
        self.use_case = WriteFileUseCase(
            self.storage,
            self.authorization,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_new_file_with_verification(self):
        result = self.use_case.execute(
            WriteFileRequest(
                path="hello.txt",
                content="مرحبا بالعالم\n",
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "write_file")

        target = self.workspace / "hello.txt"
        self.assertTrue(target.is_file())
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "مرحبا بالعالم\n",
        )
        self.assertTrue(result["evidence"]["verified"])
        self.assertFalse(result["evidence"]["backup_created"])

    def test_overwrite_creates_backup_of_previous_content(self):
        target = self.workspace / "notes.txt"
        target.write_text("old content", encoding="utf-8")

        result = self.use_case.execute(
            WriteFileRequest(
                path="notes.txt",
                content="new content",
            )
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["evidence"]["backup_created"])

        backup = self.workspace / "notes.txt.alix-backup"
        self.assertTrue(backup.is_file())
        self.assertEqual(
            backup.read_text(encoding="utf-8"),
            "old content",
        )
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "new content",
        )

    def test_creates_missing_parent_directories(self):
        result = self.use_case.execute(
            WriteFileRequest(
                path="a/b/c/deep.txt",
                content="deep",
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            (self.workspace / "a" / "b" / "c" / "deep.txt").read_text(
                encoding="utf-8"
            ),
            "deep",
        )

    def test_denies_path_outside_workspace(self):
        outside = Path(self.tmp.name).parent / "outside_write.txt"

        try:
            result = self.use_case.execute(
                WriteFileRequest(
                    path=str(outside),
                    content="secret",
                )
            )

            self.assertFalse(result["ok"])
            self.assertFalse(outside.exists())
        finally:
            outside.unlink(missing_ok=True)

    def test_denies_non_string_content(self):
        result = self.use_case.execute(
            WriteFileRequest(
                path="bad.txt",
                content=123,
            )
        )

        self.assertFalse(result["ok"])
        self.assertFalse((self.workspace / "bad.txt").exists())

    def test_denies_empty_path(self):
        result = self.use_case.execute(
            WriteFileRequest(
                path="   ",
                content="x",
            )
        )

        self.assertFalse(result["ok"])

    def test_composition_root_wires_real_controller_to_real_storage(self):
        from core.policy import Policy
        from features.file_access.composition import build_write_file_controller

        policy = Policy()
        filename = "integration_write_file_feature.txt"
        target = policy.workspace / filename

        try:
            controller = build_write_file_controller(policy)

            result = controller.handle(
                {
                    "path": filename,
                    "content": "alpha\nbeta\n",
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "write_file")
            self.assertTrue(result["evidence"]["verified"])
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "alpha\nbeta\n",
            )
        finally:
            target.unlink(missing_ok=True)
            (policy.workspace / (filename + ".alix-backup")).unlink(
                missing_ok=True
            )


class TestWriteFileAuthorizationBoundary(unittest.TestCase):
    def test_use_case_checks_authorization_before_storage(self):
        class DenyingAuthorization:
            def __init__(self):
                self.paths = []

            def can_write_file(self, path):
                self.paths.append(path)
                return False

        class ExplodingStorage:
            def write_file(self, **kwargs):
                raise AssertionError(
                    "Storage must not be called when authorization is denied"
                )

        authorization = DenyingAuthorization()
        use_case = WriteFileUseCase(
            storage=ExplodingStorage(),
            authorization=authorization,
        )

        result = use_case.execute(
            WriteFileRequest(path="secret.txt", content="x")
        )

        self.assertFalse(result["ok"])
        self.assertEqual(authorization.paths, ["secret.txt"])


class TestWriteFileUseCaseBoundary(unittest.TestCase):
    def test_use_case_delegates_to_storage_port_without_filesystem_knowledge(self):
        class SpyStorage:
            def __init__(self):
                self.calls = []

            def write_file(self, path, content):
                self.calls.append(
                    {
                        "path": path,
                        "content": content,
                    }
                )
                return {
                    "ok": True,
                    "action": "write_file",
                    "message": "spy",
                    "stdout": "",
                    "stderr": "",
                    "returncode": 0,
                    "evidence": {"verified": True},
                    "duration": 0.0,
                }

        storage = SpyStorage()

        class AllowingAuthorization:
            def can_write_file(self, path):
                return True

        use_case = WriteFileUseCase(
            storage,
            AllowingAuthorization(),
        )

        result = use_case.execute(
            WriteFileRequest(
                path="example.txt",
                content="hello",
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            storage.calls,
            [
                {
                    "path": "example.txt",
                    "content": "hello",
                }
            ],
        )


class TestWriteFileControllerBoundary(unittest.TestCase):
    def test_controller_maps_external_arguments_to_use_case_request(self):
        from features.file_access.interfaces.controllers.write_file_controller import (
            WriteFileController,
        )

        class SpyUseCase:
            def __init__(self):
                self.requests = []

            def execute(self, request):
                self.requests.append(request)
                return {"ok": True, "action": "write_file"}

        spy = SpyUseCase()
        controller = WriteFileController(spy)

        result = controller.handle(
            {
                "path": "example.txt",
                "content": "hello",
            }
        )

        self.assertEqual(
            result,
            {"ok": True, "action": "write_file"},
        )

        self.assertEqual(len(spy.requests), 1)

        request = spy.requests[0]
        self.assertIsInstance(request, WriteFileRequest)
        self.assertEqual(request.path, "example.txt")
        self.assertEqual(request.content, "hello")


class TestWriteFilePolicyAuthorizationAdapter(unittest.TestCase):
    """
    يثبت أن can_write_file() الحقيقي (PolicyAuthorizationAdapter فوق
    Policy الحقيقي) يرفض فعليًا مسارًا خارج workspace -- نفس الفجوة
    التي غطاها نظيره لقراءة الملفات.
    """

    def setUp(self):
        from features.file_access.infrastructure.adapters.policy_authorization import (
            PolicyAuthorizationAdapter,
        )

        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)

        self.policy = Policy()
        self.policy.workspace = self.workspace

        self.adapter = PolicyAuthorizationAdapter(self.policy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_allows_path_inside_workspace(self):
        self.assertTrue(self.adapter.can_write_file("new_file.txt"))
        self.assertTrue(
            self.adapter.can_write_file("sub/dir/new_file.txt")
        )

    def test_denies_path_outside_workspace(self):
        outside = Path(self.tmp.name).parent / "outside_write_secret.txt"

        self.assertFalse(
            self.adapter.can_write_file(str(outside))
        )


class TestWriteFileLiveAgentWiring(unittest.TestCase):
    """
    يثبت أن مسار الوكيل الحي (core/agent.py._execute_tool_body)
    يصل فعليًا للشريحة الجديدة لأداة write_file -- بعد إزالة فرع
    fallback القديم، لا يبقى إلا مسار الـ handlers المُهاجَرة.
    """

    def test_agent_execute_tool_body_reaches_new_slice(self):
        from core.agent import ALIXAgent
        from core.policy import Policy

        agent = ALIXAgent.__new__(ALIXAgent)
        agent.policy = Policy()

        target = agent.policy.workspace / "live_agent_write_wiring.txt"

        try:
            result = agent._execute_tool_body(
                "write_file",
                {
                    "path": "live_agent_write_wiring.txt",
                    "content": "wired\n",
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "write_file")
            self.assertTrue(result["evidence"]["verified"])
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "wired\n",
            )
        finally:
            target.unlink(missing_ok=True)
            (agent.policy.workspace / "live_agent_write_wiring.txt.alix-backup").unlink(
                missing_ok=True
            )


class TestWriteFileLiveRegistryWiring(unittest.TestCase):
    """
    يثبت أن ToolRegistry يسجّل write_file عبر الشريحة الجديدة،
    لا عبر SafeExecutor مباشرة -- أي أن نتيجة registry.execute
    تحمل بصمة الشريحة (فحص التفويض المبكر قبل التخزين).
    """

    def test_registry_write_file_goes_through_new_slice(self):
        from core.policy import Policy
        from core.registry import ToolRegistry

        policy = Policy()

        registry = ToolRegistry(policy)

        self.assertTrue(registry.has("write_file"))
        # Regression guard: the handler must be the migrated slice handler.
        # A duplicate self.register("write_file", ...) later in __init__
        # would silently overwrite it (this exact bug shipped once).
        self.assertIs(
            registry.tools["write_file"],
            registry._migrated_handlers["write_file"],
        )

        target = policy.workspace / "registry_write_wiring.txt"

        try:
            result = registry.execute(
                "write_file",
                {
                    "path": "registry_write_wiring.txt",
                    "content": "via registry\n",
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "write_file")
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "via registry\n",
            )
        finally:
            target.unlink(missing_ok=True)
            (policy.workspace / "registry_write_wiring.txt.alix-backup").unlink(
                missing_ok=True
            )


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from core.policy import Policy
from features.file_access.application.dto.read_file import (
    MIN_MAX_OUTPUT,
    ReadFileRequest,
)
from features.file_access.application.use_cases.read_file import (
    ReadFileUseCase,
)
from features.file_access.infrastructure.adapters.workspace_file_storage import (
    WorkspaceFileStorageAdapter,
)


class TestReadFileFeature(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)

        self.policy = Policy()
        self.policy.workspace = self.workspace

        self.storage = WorkspaceFileStorageAdapter(
            policy=self.policy,
            max_output=4000,
        )

        class AllowingAuthorization:
            def can_read_file(self, path):
                return True

        self.authorization = AllowingAuthorization()
        self.use_case = ReadFileUseCase(
            self.storage,
            self.authorization,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_requested_line_range(self):
        target = self.workspace / "sample.txt"

        target.write_text(
            "one\n"
            "two\n"
            "three\n"
            "four\n",
            encoding="utf-8",
        )

        result = self.use_case.execute(
            ReadFileRequest(
                path="sample.txt",
                start_line=2,
                end_line=3,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "two\nthree")
        self.assertTrue(result["evidence"]["streamed"])
        self.assertEqual(result["evidence"]["returned_lines"], 2)

    def test_denies_path_outside_workspace(self):
        outside = Path(self.tmp.name).parent / "outside.txt"
        outside.write_text(
            "secret",
            encoding="utf-8",
        )

        result = self.use_case.execute(
            ReadFileRequest(
                path=str(outside),
            )
        )

        self.assertFalse(result["ok"])

    def test_bounded_output_is_preserved(self):
        # NOTE: SafeExecutor enforces a 500-character floor on
        # max_output (a deliberate production safety limit, not a
        # bug) -- since WorkspaceFileStorageAdapter delegates to it
        # for real, this test uses a value clearly above that floor
        # instead of an unrealistic max_output=5 that the old,
        # duplicated adapter logic used to accept silently.
        target = self.workspace / "large.txt"
        target.write_text("X" * 1000 + "\n", encoding="utf-8")

        max_output = 500

        result = ReadFileUseCase(
            WorkspaceFileStorageAdapter(
                policy=self.policy,
                max_output=max_output,
            ),
            self.authorization,
        ).execute(
            ReadFileRequest(
                path="large.txt",
                max_output=max_output,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["stdout"]), max_output)
        self.assertTrue(result["evidence"]["output_truncated"])


    def test_line_count_reflects_total_lines_not_early_stop(self):
        target = self.workspace / "many_lines.txt"
        target.write_text(
            "\n".join(f"line{i}" for i in range(1, 101)) + "\n"
        )

        result = self.use_case.execute(
            ReadFileRequest(
                path="many_lines.txt",
                start_line=1,
                end_line=2,
            )
        )

        self.assertEqual(result["evidence"]["line_count"], 100)


    def test_composition_root_wires_real_controller_to_real_storage(self):
        from core.policy import Policy
        from features.file_access.composition import build_read_file_controller

        policy = Policy()
        filename = "integration_read_file_feature.txt"
        target = policy.workspace / filename

        target.write_text(
            "alpha\nbeta\ngamma\n",
            encoding="utf-8",
        )

        try:
            controller = build_read_file_controller(policy)

            result = controller.handle(
                {
                    "path": filename,
                    "start_line": 2,
                    "end_line": 3,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "read_file")
            self.assertEqual(result["stdout"], "beta\ngamma")
            self.assertEqual(result["evidence"]["path"], filename)
            self.assertEqual(result["evidence"]["returned_lines"], 2)
            self.assertEqual(result["evidence"]["line_count"], 3)
            self.assertTrue(result["evidence"]["streamed"])

        finally:
            try:
                target.unlink()
            except FileNotFoundError:
                pass


class TestReadFileAuthorizationBoundary(unittest.TestCase):
    def test_use_case_checks_authorization_before_storage(self):
        from features.file_access.application.dto.read_file import ReadFileRequest
        from features.file_access.application.use_cases.read_file import ReadFileUseCase

        class DenyingAuthorization:
            def __init__(self):
                self.paths = []

            def can_read_file(self, path):
                self.paths.append(path)
                return False

        class ExplodingStorage:
            def read_file(self, **kwargs):
                raise AssertionError(
                    "Storage must not be called when authorization is denied"
                )

        authorization = DenyingAuthorization()
        use_case = ReadFileUseCase(
            storage=ExplodingStorage(),
            authorization=authorization,
        )

        result = use_case.execute(
            ReadFileRequest(path="secret.txt")
        )

        self.assertFalse(result["ok"])
        self.assertEqual(authorization.paths, ["secret.txt"])


if __name__ == "__main__":
    unittest.main()


class TestReadFileUseCaseBoundary(unittest.TestCase):
    def test_use_case_delegates_to_storage_port_without_filesystem_knowledge(self):
        class SpyStorage:
            def __init__(self):
                self.calls = []

            def read_file(
                self,
                path,
                start_line=1,
                end_line=None,
                max_output=4000,
            ):
                self.calls.append(
                    {
                        "path": path,
                        "start_line": start_line,
                        "end_line": end_line,
                        "max_output": max_output,
                    }
                )
                return {
                    "ok": True,
                    "action": "read_file",
                    "message": "spy",
                    "stdout": "result",
                    "stderr": "",
                    "returncode": 0,
                    "evidence": {},
                    "duration": 0.0,
                }

        storage = SpyStorage()
        class AllowingAuthorization:
            def can_read_file(self, path):
                return True

        use_case = ReadFileUseCase(
            storage,
            AllowingAuthorization(),
        )

        result = use_case.execute(
            ReadFileRequest(
                path="example.txt",
                start_line=3,
                end_line=7,
                max_output=123,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "result")
        self.assertEqual(
            storage.calls,
            [
                {
                    "path": "example.txt",
                    "start_line": 3,
                    "end_line": 7,
                    "max_output": MIN_MAX_OUTPUT,
                }
            ],
        )

class TestReadFileContract(unittest.TestCase):
    def test_max_output_has_production_minimum(self):
        request = ReadFileRequest(
            path="example.txt",
            max_output=1,
        )

        self.assertEqual(
            request.normalized_max_output(),
            MIN_MAX_OUTPUT,
        )
        self.assertEqual(MIN_MAX_OUTPUT, 500)

class TestReadFileControllerBoundary(unittest.TestCase):
    def test_controller_maps_external_arguments_to_use_case_request(self):
        from features.file_access.interfaces.controllers.read_file_controller import (
            ReadFileController,
        )

        class SpyUseCase:
            def __init__(self):
                self.requests = []

            def execute(self, request):
                self.requests.append(request)
                return {"ok": True, "action": "read_file"}

        spy = SpyUseCase()
        controller = ReadFileController(spy)

        result = controller.handle(
            {
                "path": "example.txt",
                "start_line": 3,
                "end_line": 7,
                "max_output": 123,
            }
        )

        self.assertEqual(
            result,
            {"ok": True, "action": "read_file"},
        )

        self.assertEqual(len(spy.requests), 1)

        request = spy.requests[0]
        self.assertIsInstance(request, ReadFileRequest)
        self.assertEqual(request.path, "example.txt")
        self.assertEqual(request.start_line, 3)
        self.assertEqual(request.end_line, 7)
        self.assertEqual(request.max_output, 123)



class TestPolicyAuthorizationAdapter(unittest.TestCase):
    """
    اختبارات حقيقية لحد أمان فعلي: PolicyAuthorizationAdapter يغلّف
    Policy الحقيقي، لا مزيّفًا. كل الاختبارات التسعة السابقة تستخدم
    AllowingAuthorization/DenyingAuthorization المزيّفة، أو تمر
    بمسار نجاح واحد فقط عبر composition root -- لا شيء يثبت أن
    can_read_file() الحقيقي يرفض فعليًا مسارًا خارج workspace.
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
        target = self.workspace / "allowed.txt"
        target.write_text("ok", encoding="utf-8")

        self.assertTrue(self.adapter.can_read_file("allowed.txt"))

    def test_denies_path_outside_workspace(self):
        outside = Path(self.tmp.name).parent / "outside_secret.txt"
        outside.write_text("secret", encoding="utf-8")

        try:
            self.assertFalse(
                self.adapter.can_read_file(str(outside))
            )
        finally:
            outside.unlink(missing_ok=True)

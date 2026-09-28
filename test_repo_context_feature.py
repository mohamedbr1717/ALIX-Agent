"""Behavioral tests for the repo_context feature slice.

Unit tests use a fake backend; integration tests drive the real vendored
repo-context-mcp server over MCP stdio and are skipped unless it is built
(REPO_CONTEXT_MCP_DIR/dist/cli.js exists).
"""
import os
import tempfile
import unittest
from pathlib import Path

from core.policy import Policy
from features.repo_context.application.dto.pack_context import PackContextRequest
from features.repo_context.application.dto.repo_map import RepoMapRequest
from features.repo_context.application.dto.search_code import SearchCodeRequest
from features.repo_context.application.use_cases.pack_context import (
    PackContextUseCase,
    parse_packed_tokens,
)
from features.repo_context.application.use_cases.repo_map import RepoMapUseCase
from features.repo_context.application.use_cases.search_code import SearchCodeUseCase
from features.repo_context.domain.root_policy import is_root_allowed, normalize_root
from features.repo_context.infrastructure.adapters.mcp_repo_backend import (
    McpRepoBackendAdapter,
    default_server_dir,
)
from features.repo_context.infrastructure.adapters.policy_repo_authorization import (
    PolicyRepoAuthorizationAdapter,
)

SERVER_BUILT = (Path(default_server_dir()) / "dist" / "cli.js").is_file()


class FakeBackend:
    """Explodes if called: used to prove denied paths never reach it."""

    def repo_map(self, *a, **k):
        raise AssertionError("backend must not be called on deny")

    def search_code(self, *a, **k):
        raise AssertionError("backend must not be called on deny")

    def pack_context(self, *a, **k):
        raise AssertionError("backend must not be called on deny")


class FakeAuthorization:
    def __init__(self, allowed=("/allowed",), default="/allowed"):
        self._allowed = allowed
        self._default = default

    def default_root(self):
        return self._default

    def is_root_allowed(self, root):
        return is_root_allowed(root, list(self._allowed))


class TestRootPolicy(unittest.TestCase):
    def test_allows_exact_root_and_subdirectory(self):
        self.assertTrue(is_root_allowed("/a/repo", ["/a/repo"]))
        self.assertTrue(is_root_allowed("/a/repo/sub/dir", ["/a/repo"]))

    def test_denies_sibling_parent_and_outside(self):
        self.assertFalse(is_root_allowed("/a/other", ["/a/repo"]))
        self.assertFalse(is_root_allowed("/a", ["/a/repo"]))
        self.assertFalse(is_root_allowed("/etc/passwd", ["/a/repo"]))

    def test_denies_traversal_and_empty(self):
        self.assertFalse(is_root_allowed("/a/repo/../../etc", ["/a/repo"]))
        self.assertFalse(is_root_allowed("", ["/a/repo"]))
        self.assertFalse(is_root_allowed("/a/repo", []))

    def test_normalize_expands_user(self):
        home = str(Path.home())
        self.assertEqual(normalize_root("~/x"), str(Path(home, "x")))


class TestAuthorizationAdapter(unittest.TestCase):
    def setUp(self):
        self.policy = Policy()

    def test_allowlist_covers_base_dir_and_workspace(self):
        auth = PolicyRepoAuthorizationAdapter(self.policy)
        self.assertIn(
            normalize_root(str(self.policy.base_dir)), auth.allowed_roots
        )
        self.assertTrue(auth.is_root_allowed(str(self.policy.base_dir)))
        self.assertTrue(
            auth.is_root_allowed(str(Path(self.policy.base_dir) / "core"))
        )

    def test_denies_outside_allowlist(self):
        auth = PolicyRepoAuthorizationAdapter(self.policy)
        self.assertFalse(auth.is_root_allowed("/etc"))
        self.assertFalse(auth.is_root_allowed(""))

    def test_default_root_is_base_dir(self):
        auth = PolicyRepoAuthorizationAdapter(self.policy)
        self.assertEqual(
            auth.default_root(), normalize_root(str(self.policy.base_dir))
        )

    def test_env_extra_roots(self):
        os.environ["ALIX_REPO_CONTEXT_ROOTS"] = "/tmp/extra-rc"
        try:
            auth = PolicyRepoAuthorizationAdapter(self.policy)
            self.assertTrue(auth.is_root_allowed("/tmp/extra-rc/sub"))
        finally:
            del os.environ["ALIX_REPO_CONTEXT_ROOTS"]


class TestUseCaseDenials(unittest.TestCase):
    def test_repo_map_denied_outside_root_never_touches_backend(self):
        uc = RepoMapUseCase(FakeAuthorization(), FakeBackend())
        result = uc.execute(RepoMapRequest(root="/etc"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "repo_map")
        self.assertIn("النطاق المسموح", result["message"])

    def test_search_code_empty_query_denied(self):
        uc = SearchCodeUseCase(FakeAuthorization(), FakeBackend())
        result = uc.execute(SearchCodeRequest(query="   "))
        self.assertFalse(result["ok"])
        self.assertIn("فارغ", result["message"])

    def test_search_code_denied_outside_root(self):
        uc = SearchCodeUseCase(FakeAuthorization(), FakeBackend())
        result = uc.execute(SearchCodeRequest(query="x", root="/etc"))
        self.assertFalse(result["ok"])

    def test_pack_context_denied_outside_root(self):
        uc = PackContextUseCase(FakeAuthorization(), FakeBackend())
        result = uc.execute(PackContextRequest(root="/etc"))
        self.assertFalse(result["ok"])

    def test_repo_map_uses_default_root_when_omitted(self):
        class FakeOkBackend:
            def repo_map(self, root, max_depth, max_entries):
                assert root == "/allowed", root
                return {"ok": True, "text": "MAP", "error": ""}

        uc = RepoMapUseCase(FakeAuthorization(), FakeOkBackend())
        result = uc.execute(RepoMapRequest(root=""))
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "MAP")
        self.assertEqual(result["evidence"]["root"], "/allowed")


class TestBackendFailsClosed(unittest.TestCase):
    def test_missing_server_dir_reports_build_instructions(self):
        backend = McpRepoBackendAdapter(server_dir="/nonexistent-rc-dir")
        result = backend.repo_map("/allowed", 6, 400)
        self.assertFalse(result["ok"])
        self.assertIn("npm run build", result["error"])


class TestParsePackedTokens(unittest.TestCase):
    def test_parses_header(self):
        md = "# Context pack\nFiles: 2 · ~1234 tokens · 5000 bytes\n"
        self.assertEqual(parse_packed_tokens(md), 1234)

    def test_none_when_absent(self):
        self.assertIsNone(parse_packed_tokens("no header here"))


@unittest.skipUnless(SERVER_BUILT, "repo-context-mcp not built (npm run build)")
class TestMcpServerIntegration(unittest.TestCase):
    """Drive the REAL vendored server over MCP stdio."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fixture = Path(self.tmp.name)
        (self.fixture / "src").mkdir()
        (self.fixture / "src" / "main.py").write_text(
            "def hello_alix():\n    return 'hi'\n", encoding="utf-8"
        )
        (self.fixture / "src" / "util.py").write_text(
            "def helper():\n    pass\n", encoding="utf-8"
        )
        (self.fixture / "ignored_secret.py").write_text(
            "SECRET = 1\n", encoding="utf-8"
        )
        (self.fixture / ".gitignore").write_text(
            "ignored_secret.py\n", encoding="utf-8"
        )
        (self.fixture / "README.md").write_text("# fixture\n", encoding="utf-8")

        os.environ["ALIX_REPO_CONTEXT_ROOTS"] = str(self.fixture)
        self.policy = Policy()
        self.auth = PolicyRepoAuthorizationAdapter(self.policy)
        self.backend = McpRepoBackendAdapter(timeout=60.0)
        self.addCleanup(self.backend.close)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("ALIX_REPO_CONTEXT_ROOTS", None)

    def test_repo_map_lists_tree_and_honors_gitignore(self):
        uc = RepoMapUseCase(self.auth, self.backend)
        result = uc.execute(RepoMapRequest(root=str(self.fixture)))
        self.assertTrue(result["ok"], result.get("message"))
        self.assertIn("src/main.py", result["stdout"])
        # tree children render as basenames under their directory node
        self.assertIn("src/", result["stdout"])
        self.assertIn("util.py", result["stdout"])
        self.assertNotIn("ignored_secret.py", result["stdout"])

    def test_search_code_finds_hit_with_path_and_line(self):
        uc = SearchCodeUseCase(self.auth, self.backend)
        result = uc.execute(
            SearchCodeRequest(query="hello_alix", root=str(self.fixture))
        )
        self.assertTrue(result["ok"], result.get("message"))
        self.assertIn("src/main.py:1", result["stdout"])

    def test_pack_context_respects_token_budget(self):
        uc = PackContextUseCase(self.auth, self.backend)
        result = uc.execute(
            PackContextRequest(root=str(self.fixture), max_tokens=1500, max_files=10)
        )
        self.assertTrue(result["ok"], result.get("message"))
        packed = result["evidence"].get("packed_tokens")
        self.assertIsNotNone(packed)
        self.assertLessEqual(packed, 1500)
        self.assertTrue(result["evidence"]["within_budget"])
        self.assertIn("src/main.py", result["stdout"])


class TestBridgeRegistration(unittest.TestCase):
    def test_bridge_exposes_three_tools(self):
        from core.feature_bridge import build_migrated_tool_handlers

        handlers = build_migrated_tool_handlers(Policy())
        for name in ("repo_map", "search_code", "pack_context"):
            self.assertIn(name, handlers)
            self.assertTrue(callable(handlers[name]))


class TestPolicyGates(unittest.TestCase):
    def test_tool_allowed_and_read_level(self):
        policy = Policy()
        for name in ("repo_map", "search_code", "pack_context"):
            self.assertTrue(policy.tool_allowed(name), name)
            self.assertEqual(policy.tool_permission(name), "read", name)

    def test_argument_schema_accepts_valid_calls(self):
        policy = Policy()
        self.assertTrue(
            policy.validate_tool_arguments(
                "repo_map", {"root": "/a", "max_depth": 3}
            )
        )
        self.assertTrue(
            policy.validate_tool_arguments(
                "search_code", {"query": "hello", "root": "/a"}
            )
        )
        self.assertTrue(
            policy.validate_tool_arguments(
                "pack_context",
                {"root": "/a", "focus": ["auth"], "max_tokens": 2000},
            )
        )

    def test_argument_schema_rejects_unknown_or_wrong_types(self):
        policy = Policy()
        # unknown argument
        self.assertFalse(
            policy.validate_tool_arguments("repo_map", {"root": "/a", "evil": 1})
        )
        # missing required
        self.assertFalse(policy.validate_tool_arguments("search_code", {"root": "/a"}))
        # wrong type (bool is not int)
        self.assertFalse(
            policy.validate_tool_arguments("repo_map", {"max_depth": True})
        )
        # wrong type (str is not list)
        self.assertFalse(
            policy.validate_tool_arguments("pack_context", {"focus": "auth"})
        )


if __name__ == "__main__":
    unittest.main()

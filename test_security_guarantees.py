"""Security guarantees — every documented guarantee gets a real test (point 4).

Covers the guarantees from SECURITY_FIXES.md that previously had zero
test coverage: memory file permissions, secret redaction, and the
registry capability gate.
"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.memory import Memory
from core.policy import Policy
from core.registry import ToolRegistry


def make_policy() -> Policy:
    policy = Policy()
    policy.workspace = Path(tempfile.mkdtemp()).resolve()
    return policy


class TestMemoryFilePermissions(unittest.TestCase):
    """SECURITY_FIXES.md #9: memory.json restricted to 0600."""

    def test_memory_file_is_owner_only(self):
        tmp = Path(tempfile.mkdtemp()) / "memory.json"
        mem = Memory(path=tmp)
        mem.add_fact("test fact")
        mode = stat.S_IMODE(os.stat(tmp).st_mode)
        self.assertEqual(mode, 0o600,
                         f"memory.json has {oct(mode)}, expected 0o600")

    def test_backup_file_is_owner_only(self):
        tmp = Path(tempfile.mkdtemp()) / "memory.json"
        mem = Memory(path=tmp)
        mem.add_fact("first")
        mem.add_fact("second")  # triggers backup write path
        bak = tmp.with_suffix(".json.bak")
        if bak.exists():
            mode = stat.S_IMODE(os.stat(bak).st_mode)
            self.assertEqual(mode, 0o600,
                             f"backup has {oct(mode)}, expected 0o600")


class TestSecretRedaction(unittest.TestCase):
    """SECURITY_FIXES.md #8: _sanitize_text redacts known secret shapes."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp()) / "memory.json"
        self.mem = Memory(path=tmp)

    def test_aws_key_redacted(self):
        out = self.mem._sanitize_text("key AKIAIOSFODNN7EXAMPLE here")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)
        self.assertIn("[REDACTED_AWS_KEY]", out)

    def test_api_key_redacted(self):
        out = self.mem._sanitize_text("token sk-abc123XYZ789qwerty456 end")
        self.assertNotIn("sk-abc123XYZ789qwerty456", out)
        self.assertIn("[REDACTED_API_KEY]", out)

    def test_github_token_redacted(self):
        out = self.mem._sanitize_text("ghp_12345678901234567890")
        self.assertNotIn("ghp_12345678901234567890", out)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", out)

    def test_private_key_block_redacted(self):
        pem = ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n"
               "-----END RSA PRIVATE KEY-----")
        out = self.mem._sanitize_text(pem)
        self.assertNotIn("MIIEowIBAAKCAQEA", out)
        self.assertIn("[REDACTED_PRIVATE_KEY]", out)

    def test_bearer_token_redacted(self):
        out = self.mem._sanitize_text("auth Bearer abc123XYZ789qwerty ok")
        self.assertNotIn("Bearer abc123XYZ789qwerty", out)
        self.assertIn("Bearer [REDACTED_TOKEN]", out)

    def test_password_assignment_redacted(self):
        out = self.mem._sanitize_text("config password=supersecret123 done")
        self.assertNotIn("supersecret123", out)

    def test_clean_text_untouched(self):
        text = "just a normal memory about groceries"
        self.assertEqual(self.mem._sanitize_text(text), text)

    def test_fact_persisted_redacted(self):
        self.mem.add_fact("my key is sk-abc123XYZ789qwerty456 really")
        raw = tmp_read(self.mem.path)
        self.assertNotIn("sk-abc123XYZ789qwerty456", raw)


def tmp_read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestRegistryCapabilityGate(unittest.TestCase):
    """SECURITY_FIXES.md #6: disabled capabilities denied at dispatch."""

    def test_disabled_capability_denied_through_execute(self):
        policy = make_policy()
        # run_python is disabled by default (Policy._config: run_python=False)
        self.assertFalse(policy.capability_allowed("run_python"))
        registry = ToolRegistry(policy)
        result = registry.execute("run_python", {"code": "1+1"})
        self.assertFalse(result["ok"])
        self.assertIn("معطلة", result["message"])

    def test_enabled_tool_passes_capability_gate(self):
        policy = make_policy()
        registry = ToolRegistry(policy)
        # read_file capability is enabled; the gate must not deny it
        self.assertTrue(policy.capability_allowed("read_file"))
        # Direct gate check: enabled capability is not the denial reason
        result = registry.execute("read_file", {"path": "/nonexistent_xyz"})
        # May fail on arguments/FS, but must NOT fail on capability
        self.assertNotIn("معطلة", result.get("message", ""))


if __name__ == "__main__":
    unittest.main()

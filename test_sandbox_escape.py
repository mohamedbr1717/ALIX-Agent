#!/usr/bin/env python3
"""Adversarial test: can a script inside ProotSandbox escape?

The test plants a canary file OUTSIDE the sandbox workspace, then runs
a malicious script inside the sandbox that tries to read it via:
  1. the direct host absolute path
  2. /proc/self/root + host path (classic proot escape vector)
  3. '..' traversal from /workspace

The sandbox passes only if ALL vectors fail (script reports CONTAINED).

Skipped when proot is unavailable (SandboxUnavailable) — the sandbox
itself is fail-closed, and there is nothing to adversarially test.

Run from the repo root: python3 -m pytest test_sandbox_escape.py -q
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.executor import ProotSandbox, SandboxUnavailable

_MALICIOUS_SCRIPT = r'''
import os
import sys

canary = sys.argv[1]
expected = sys.argv[2]

def try_read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return None

vectors = {
    "direct": canary,
    "proc_self_root": "/proc/self/root" + canary,
    "dotdot": "/workspace/../.." + canary,
}

escaped_via = None
for name, path in vectors.items():
    content = try_read(path)
    if content == expected:
        escaped_via = name
        break

if escaped_via:
    print(f"ESCAPED via {escaped_via}")
else:
    print("CONTAINED")

# Also try to WRITE outside the workspace.
try:
    with open("/proc/self/root" + canary + ".pwned", "w") as fh:
        fh.write("pwned")
    print("WRITE_ESCAPED")
except Exception:
    print("WRITE_CONTAINED")
'''


class TestSandboxEscape(unittest.TestCase):
    def test_cannot_read_or_write_outside_workspace(self) -> None:
        if shutil.which("proot") is None:
            self.skipTest("proot not installed")
        with tempfile.TemporaryDirectory(
            prefix="alix-escape-workspace-"
        ) as ws, tempfile.TemporaryDirectory(
            prefix="alix-escape-outside-"
        ) as outside:
            workspace = Path(ws)
            canary = Path(outside) / "canary.txt"
            canary.write_text("top-secret-canary", encoding="utf-8")

            script = workspace / "evil.py"
            script.write_text(_MALICIOUS_SCRIPT, encoding="utf-8")

            try:
                sandbox = ProotSandbox(workspace=workspace)
            except SandboxUnavailable as exc:
                self.skipTest(str(exc))

            result = sandbox.run(
                script,
                script_args=[str(canary), "top-secret-canary"],
                timeout=30,
            )
            stdout = result.get("stdout", "")
            self.assertIn(
                "CONTAINED",
                stdout,
                f"sandbox escape! stdout={stdout!r} "
                f"stderr={result.get('stderr', '')!r}",
            )
            self.assertNotIn("ESCAPED via", stdout)
            self.assertIn("WRITE_CONTAINED", stdout)
            # The canary must be untouched.
            self.assertEqual(
                canary.read_text(encoding="utf-8"), "top-secret-canary"
            )
            self.assertFalse((Path(str(canary) + ".pwned")).exists())


if __name__ == "__main__":
    unittest.main()

"""Behavioral tests for the pure domain rule domain.rules.sensitive_paths.

The rule is a pure function: (path, workspace, sets) -> bool.
No Policy, no I/O. The parity + rebinding tests guard the Policy wiring.
"""
from functools import partial
from pathlib import Path

import pytest

from domain.rules.sensitive_paths import is_sensitive_path

NAMES = {"credentials.json", ".env", "id_rsa", "secrets.json"}
DIRS = {".ssh", ".aws"}
EXTS = {".pem", ".key"}


@pytest.fixture
def check(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return partial(
        is_sensitive_path,
        workspace=ws,
        sensitive_names=frozenset(NAMES),
        sensitive_directories=frozenset(DIRS),
        sensitive_extensions=frozenset(EXTS),
    ), ws


def test_sensitive_name_in_any_component(check):
    decide, ws = check
    assert decide(ws / "a" / "b" / "credentials.json")
    assert decide(ws / ".env")


def test_sensitive_directory_nested(check):
    decide, ws = check
    assert decide(ws / ".ssh" / "config")
    assert decide(ws / ".aws" / "credentials")


def test_sensitive_extension_case_insensitive(check):
    decide, ws = check
    assert decide(ws / "backup.PEM")
    assert decide(ws / "server.Key")


def test_outside_workspace_is_forbidden(check):
    decide, ws = check
    assert decide(ws.parent / "other" / "x.txt")


def test_workspace_root_itself_is_fine(check):
    decide, ws = check
    assert not decide(ws)


def test_normal_file_is_fine(check):
    decide, ws = check
    assert not decide(ws / "notes.txt")
    assert not decide(ws / "src" / "main.py")


def test_non_sensitive_dotfile_is_fine(check):
    # Guards against over-blocking: not every dotfile is sensitive.
    decide, ws = check
    assert not decide(ws / ".gitignore")


def test_name_match_must_be_exact_component(check):
    decide, ws = check
    assert not decide(ws / "my_credentials.json.bak")
    assert not decide(ws / "env.txt")


def test_plain_ssh_dir_without_dot_is_fine(check):
    decide, ws = check
    assert not decide(ws / "ssh" / "config")


def test_accepts_string_paths(check):
    decide, ws = check
    assert decide(str(ws / ".env"))
    assert not decide(str(ws / "notes.txt"))


def test_policy_delegation_parity():
    """Policy.is_sensitive_path must match the pure function on its own config."""
    from core.policy import Policy

    policy = Policy()
    battery = [
        "notes.txt",
        ".env",
        "sub/credentials.json",
        ".ssh/config",
        "backup.PEM",
        ".gitignore",
        "a/b/c.txt",
        "../outside.txt",
        "id_rsa",
        ".aws/x",
    ]
    for rel in battery:
        p = policy.workspace / rel
        expected = is_sensitive_path(
            p,
            policy.workspace,
            policy.sensitive_names,
            policy.sensitive_directories,
            policy.sensitive_extensions,
        )
        assert policy.is_sensitive_path(p) == expected, rel


def test_policy_workspace_rebinding_after_init(tmp_path):
    """Regression (2026-09-22): Policy.workspace rebound after __init__
    (as the file_access adapter tests do) must be honored, not frozen."""
    from core.policy import Policy

    policy = Policy()
    policy.workspace = tmp_path / "ws2"
    policy.workspace.mkdir()

    assert policy.is_sensitive_path(policy.workspace / "notes.txt") is False
    assert policy.is_sensitive_path(policy.workspace / ".env") is True
    assert policy.is_sensitive_path(tmp_path / "elsewhere" / "x") is True

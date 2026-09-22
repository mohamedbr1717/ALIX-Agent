"""Behavioral tests for the pure domain rule domain.rules.confirmation.

The rule is a pure function: (tool_name, tool_permissions) -> bool.
No Policy, no I/O. The parity test guards the Policy wiring.
"""
from domain.rules.confirmation import CONFIRMING_PERMISSIONS, requires_confirmation

PERMS = {
    "write_file": "write",
    "run_command": "execute",
    "delete_file": "destructive",
    "read_file": "read",
    "list_files": "read",
    "web_search": "read",
}


def test_write_execute_destructive_require_confirmation():
    assert requires_confirmation("write_file", PERMS) is True
    assert requires_confirmation("run_command", PERMS) is True
    assert requires_confirmation("delete_file", PERMS) is True


def test_read_does_not_require_confirmation():
    assert requires_confirmation("read_file", PERMS) is False
    assert requires_confirmation("web_search", PERMS) is False


def test_unknown_tool_does_not_require_confirmation():
    assert requires_confirmation("no_such_tool", PERMS) is False


def test_empty_permissions_does_not_require_confirmation():
    assert requires_confirmation("write_file", {}) is False


def test_non_string_tool_name_is_rejected():
    assert requires_confirmation(None, PERMS) is False
    assert requires_confirmation(123, PERMS) is False
    assert requires_confirmation(["write_file"], PERMS) is False


def test_confirming_permissions_set_documents_the_rule():
    assert CONFIRMING_PERMISSIONS == frozenset({"write", "execute", "destructive"})


def test_policy_delegation_parity():
    """Policy.requires_confirmation must match the pure function on its own config."""
    from core.policy import Policy

    policy = Policy()
    names = list(policy.tool_permissions) + ["no_such_tool", "", None, 42]
    for name in names:
        expected = requires_confirmation(name, policy.tool_permissions)
        assert policy.requires_confirmation(name) is expected, name

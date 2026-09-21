"""Critique #4 - evidence priority: static checks that the addendum exists
and is wired into the system prompt. Run from repo root:
    python -m pytest test_evidence_priority.py -q
"""
import re
from pathlib import Path

AGENT = Path(__file__).parent / "core" / "agent.py"


def _src():
    return AGENT.read_text(encoding="utf-8")


def _system_fn(src):
    m = re.search(r"def build_system_message\(self\):.*?(?=\n    def |\nclass |\Z)", src, re.S)
    assert m, "build_system_message not found"
    return m.group(0)


def test_addendum_defined_with_rules():
    src = _src()
    assert "EVIDENCE_PRIORITY_ADDENDUM" in src
    for kw in ("web_search", "internal knowledge", "locally installed", "source of truth"):
        assert kw in src, "missing rule keyword: %s" % kw


def test_addendum_wired_into_system_message():
    fn = _system_fn(_src())
    assert re.search(r"\+\s*EVIDENCE_PRIORITY_ADDENDUM", fn), \
        "addendum not concatenated into the returned system prompt"


def test_addendum_placed_after_guard():
    fn = _system_fn(_src())
    assert fn.index("SYSTEM_GUARD_ADDENDUM") < fn.index("EVIDENCE_PRIORITY_ADDENDUM")

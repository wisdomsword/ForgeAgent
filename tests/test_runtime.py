"""Unit tests for the utils runtime state mechanism (M3-1)."""

from forgeagent.runtime import Runtime


def test_set_then_get_state():
    rt = Runtime()
    rt.set_state("x", 42)
    assert rt.get_state("x") == 42


def test_get_state_default_when_absent():
    rt = Runtime()
    assert rt.get_state("missing") is None
    assert rt.get_state("missing", "fallback") == "fallback"


def test_state_persists_across_calls():
    # One Runtime shared across blocks: state set in an earlier "block" (call) is
    # visible to a later one.
    rt = Runtime()
    rt.set_state("step1", [1, 2, 3])
    # ... a later block reads it
    assert rt.get_state("step1") == [1, 2, 3]


def test_has_state():
    rt = Runtime()
    assert rt.has_state("k") is False
    rt.set_state("k", None)  # even a None value counts as set
    assert rt.has_state("k") is True


def test_set_result_structured():
    rt = Runtime()
    assert rt.result is None
    rt.set_result(True, rows=10, path="out.json")
    assert rt.result == {"success": True, "rows": 10, "path": "out.json"}


def test_set_result_failure():
    rt = Runtime()
    rt.set_result(False, error="boom")
    assert rt.result["success"] is False
    assert rt.result["error"] == "boom"


def test_shared_state_dict_reflects_mutations():
    shared: dict = {}
    rt = Runtime(state=shared)
    rt.set_state("a", 1)
    # The backend can read the same dict it passed in (used for cross-block persistence).
    assert shared["a"] == 1
    assert rt.state is shared

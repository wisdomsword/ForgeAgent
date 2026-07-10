"""Unit tests for executor backends (M3-2)."""

from forgeagent.executor import ExecResult, ExecutorBackend, TrustedBackend
from forgeagent.runtime import Runtime


def test_trusted_is_an_executor_backend():
    assert isinstance(TrustedBackend(), ExecutorBackend)


def test_execute_captures_stdout():
    result = TrustedBackend().execute("print('hello')", Runtime())
    assert result.success is True
    assert result.stdout.strip() == "hello"
    assert result.error is None


def test_globals_persist_across_blocks():
    backend = TrustedBackend()
    rt = Runtime()
    backend.execute("shared_value = 21 * 2", rt)
    # A later block sees the variable defined by the earlier one.
    result = backend.execute("print(shared_value)", rt)
    assert result.success is True
    assert result.stdout.strip() == "42"


def test_set_state_visible_across_blocks_via_utils():
    backend = TrustedBackend()
    rt = Runtime()
    backend.execute("utils.set_state('total', 100)", rt)
    result = backend.execute("print(utils.get_state('total'))", rt)
    assert result.stdout.strip() == "100"
    assert rt.get_state("total") == 100


def test_exception_captured_not_crashing_host():
    result = TrustedBackend().execute("1 / 0", Runtime())
    assert result.success is False
    assert "ZeroDivisionError" in result.error


def test_exception_preserves_stdout_before_failure():
    code = "print('before')\nraise ValueError('boom')"
    result = TrustedBackend().execute(code, Runtime())
    assert result.success is False
    assert result.stdout.strip() == "before"
    assert "ValueError: boom" in result.error


def test_syntax_error_reported_readably():
    result = TrustedBackend().execute("def broken(:", Runtime())
    assert result.success is False
    assert "SyntaxError" in result.error


def test_stderr_captured():
    code = "import sys\nsys.stderr.write('warn')"
    result = TrustedBackend().execute(code, Runtime())
    assert result.success is True
    assert result.stderr == "warn"


def test_exec_result_is_serializable():
    # ExecResult is a pydantic model — usable in feedback rendering / logging.
    r = ExecResult(success=True, stdout="x")
    assert r.model_dump()["success"] is True

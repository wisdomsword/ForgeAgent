"""Unit tests for the AST static policy engine (M4-1).

The static layer is reporting-only (weak constraint, not a security boundary). These
tests assert detection + feedback rendering + pluggability, not enforcement.
"""

import ast

from forgeagent.policy import (
    AnalysisResult,
    CodeAnalyzer,
    DynamicImportRule,
    ForbiddenImportRule,
    Issue,
    Rule,
    default_rules,
)


def test_clean_code_has_no_issues():
    result = CodeAnalyzer().analyze("x = 1 + 2\nprint(x)")
    assert result.clean is True
    assert result.issues == []


def test_forbidden_import_detected():
    result = CodeAnalyzer().analyze("import ctypes")
    assert any(i.rule == "forbidden-import" for i in result.issues)


def test_forbidden_import_from_detected():
    result = CodeAnalyzer().analyze("from subprocess import run")
    assert any(i.rule == "forbidden-import" for i in result.issues)


def test_forbidden_submodule_import_detected():
    # os.path is fine; socket.something is flagged via top-level name.
    result = CodeAnalyzer().analyze("import socket.foo")
    assert any(i.rule == "forbidden-import" for i in result.issues)


def test_dynamic_importlib_detected_t7():
    # T7: dynamic import that static import-statement checks would miss.
    result = CodeAnalyzer().analyze("import importlib\nm = importlib.import_module('os')")
    assert any(i.rule == "dynamic-import" for i in result.issues)


def test_dunder_import_detected_t7():
    result = CodeAnalyzer().analyze("m = __import__('os')")
    assert any(i.rule == "dynamic-import" for i in result.issues)


def test_syntax_error_reported():
    result = CodeAnalyzer().analyze("def broken(:")
    assert result.clean is False
    assert "SyntaxError" in result.syntax_error


def test_feedback_readable_for_issues():
    result = CodeAnalyzer().analyze("import ctypes\nm = __import__('os')")
    fb = CodeAnalyzer().feedback(result)
    assert "static check" in fb
    assert "forbidden-import" in fb
    assert "dynamic-import" in fb


def test_feedback_empty_when_clean():
    result = CodeAnalyzer().analyze("y = 5")
    assert CodeAnalyzer().feedback(result) == ""


def test_feedback_for_syntax_error():
    result = CodeAnalyzer().analyze("x = (")
    assert "SyntaxError" in CodeAnalyzer().feedback(result)


def test_rules_are_pluggable():
    class NoEvalRule(Rule):
        name = "no-eval"

        def check(self, node):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "eval":
                    return Issue(rule=self.name, message="eval() flagged", line=node.lineno)
            return None

    analyzer = CodeAnalyzer(rules=[])
    analyzer.register(NoEvalRule())
    result = analyzer.analyze("eval('1+1')")
    assert any(i.rule == "no-eval" for i in result.issues)


def test_default_rules_present():
    rules = default_rules()
    names = {r.name for r in rules}
    assert "forbidden-import" in names
    assert "dynamic-import" in names


def test_analysis_result_clean_property():
    assert AnalysisResult(issues=[]).clean is True
    assert AnalysisResult(issues=[Issue(rule="r", message="m")]).clean is False
    assert AnalysisResult(issues=[], syntax_error="SyntaxError: x").clean is False


def test_static_rules_are_reporting_not_blocking():
    # ForbiddenImportRule/DynamicImportRule only produce Issues; verify no exception
    # and no mutation of the analyzed source semantics (analyze returns a result object).
    analyzer = CodeAnalyzer()
    result = analyzer.analyze("import ctypes")
    assert isinstance(result, AnalysisResult)
    # Direct rule call returns an Issue, never raises or mutates.
    issue = ForbiddenImportRule().check(ast.parse("import ctypes").body[0])
    assert issue is not None
    assert DynamicImportRule().check(ast.parse("x=1").body[0]) is None

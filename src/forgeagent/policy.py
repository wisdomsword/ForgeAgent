"""AST static policy engine: check code, emit LLM feedback, pluggable rules.

See ACTION_PLAN §二 (borrow agent's code_analyzer.py, extend) and docs/threat-model.md.
This is the STATIC weak-constraint layer — it gives the model early feedback and catches
obvious misuse, but is NOT a security boundary (it is Turing-complete-bypassable; T7 is
the example). Real enforcement is the restricted execution backend (see executor.py).

Rules are pluggable: subclass Rule and register it. The engine walks the AST once and
collects Issues; it never mutates or blocks — reporting only.
"""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod

from pydantic import BaseModel


class Issue(BaseModel):
    """One detected problem in a code block."""

    rule: str
    message: str
    line: int | None = None
    # severity is advisory only — the static layer never blocks execution.
    severity: str = "warning"


class Rule(ABC):
    """A pluggable check. Inspects a node, optionally returns an Issue (no mutation)."""

    name: str = "rule"

    @abstractmethod
    def check(self, node: ast.AST) -> Issue | None:
        """Return an Issue if this node violates the rule, else None."""


class ForbiddenImportRule(Rule):
    """Flag imports of modules that enable host escape (static warning only)."""

    name = "forbidden-import"
    FORBIDDEN = {"ctypes", "subprocess", "socket"}

    def check(self, node: ast.AST) -> Issue | None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in self.FORBIDDEN:
                    return Issue(
                        rule=self.name,
                        message=f"import of {alias.name!r} is flagged; "
                        f"restricted backend limits what it can reach",
                        line=node.lineno,
                    )
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in self.FORBIDDEN:
                return Issue(
                    rule=self.name,
                    message=f"import from {node.module!r} is flagged",
                    line=node.lineno,
                )
        return None


class DynamicImportRule(Rule):
    """Detect dynamic imports (importlib.import_module / __import__) — closes the T7
    gap that agent's ForbiddenImportRule (static import statements only) misses."""

    name = "dynamic-import"

    def check(self, node: ast.AST) -> Issue | None:
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        # __import__(...)
        if isinstance(func, ast.Name) and func.id == "__import__":
            return Issue(
                rule=self.name,
                message="dynamic __import__() detected; static import checks can be "
                "bypassed this way — restricted backend still limits reach",
                line=node.lineno,
            )
        # importlib.import_module(...)
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            return Issue(
                rule=self.name,
                message="importlib.import_module() detected; dynamic import can bypass "
                "static checks — restricted backend still limits reach",
                line=node.lineno,
            )
        return None


class AnalysisResult(BaseModel):
    """Outcome of analyzing one code block."""

    issues: list[Issue]
    syntax_error: str | None = None

    @property
    def clean(self) -> bool:
        return not self.issues and self.syntax_error is None


class CodeAnalyzer:
    """Runs registered rules over a code block in a single AST walk (reporting only)."""

    def __init__(self, rules: list[Rule] | None = None):
        self._rules: list[Rule] = rules if rules is not None else default_rules()

    def register(self, rule: Rule) -> None:
        """Add a rule (pluggable extension point)."""
        self._rules.append(rule)

    def analyze(self, code: str) -> AnalysisResult:
        """Parse and check `code`. A syntax error short-circuits (unfixable, reported)."""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return AnalysisResult(
                issues=[], syntax_error=f"SyntaxError: {exc.msg} (line {exc.lineno})"
            )
        issues: list[Issue] = []
        for node in ast.walk(tree):
            for rule in self._rules:
                issue = rule.check(node)
                if issue is not None:
                    issues.append(issue)
        return AnalysisResult(issues=issues)

    def feedback(self, result: AnalysisResult) -> str:
        """Render issues into readable LLM feedback; empty string if clean."""
        if result.syntax_error:
            return f"[static check] {result.syntax_error}"
        if not result.issues:
            return ""
        lines = ["[static check] potential issues (advisory, not blocking):"]
        for issue in result.issues:
            loc = f" (line {issue.line})" if issue.line else ""
            lines.append(f"  - [{issue.rule}]{loc} {issue.message}")
        return "\n".join(lines)


def default_rules() -> list[Rule]:
    """The default rule set: forbidden imports + dynamic-import (T7) detection."""
    return [ForbiddenImportRule(), DynamicImportRule()]

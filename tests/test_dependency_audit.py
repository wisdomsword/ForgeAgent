"""Exercise the audited OpenSpec exception's scope and expiry."""

import copy

from scripts.audit_dependencies import PICOMATCH_ADVISORY, npm_gate


def test_npm_audit_exception_applies_only_to_the_reviewed_advisory_and_version():
    packages = {"node_modules/picomatch": {"version": "2.3.2"}}
    report = {
        "auditReportVersion": 2,
        "metadata": {"vulnerabilities": {"total": 2}},
        "vulnerabilities": {
            "parent": {"via": ["picomatch"]},
            "picomatch": {
                "nodes": ["node_modules/picomatch"],
                "via": [{"url": PICOMATCH_ADVISORY}],
            },
        },
    }
    assert npm_gate(report, packages, "2026-12-17")
    assert not npm_gate(report, packages, "2026-12-18")
    assert not npm_gate(report, {"node_modules/picomatch": {"version": "3.0.0"}}, "2026-12-17")

    additional = copy.deepcopy(report)
    additional["vulnerabilities"]["picomatch"]["via"].append({"url": "https://example.test/other"})
    assert not npm_gate(additional, packages, "2026-12-17")
    assert not npm_gate({}, packages, "2026-12-17")
    assert not npm_gate({**report, "error": {}}, packages, "2026-12-17")

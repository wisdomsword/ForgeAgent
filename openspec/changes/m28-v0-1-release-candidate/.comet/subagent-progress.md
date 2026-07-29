# M28 Subagent Progress

- Plan task: Task 2: 真实 wheel packaging 与 Linux Docker 门禁
- OpenSpec tasks: 2.3, 3.1, 3.2
- Phase: done
- Review mode: thorough
- Review/fix round: 1/2
- Base commit: 08c9c64
- Implementer: DONE_WITH_CONCERNS
- Implementation commit: 6bc760a5a5b8fdcc18186a6b9b44749324776569
- Changed files: `.gitlab-ci.yml`, `tests/test_packaging.py`, `tests/test_m28_release_ci.py`
- RED/GREEN evidence: release CI/packaging RED on absent RC artifact/harness; GREEN 9 passed in 37.34s including real wheel harness and adjacent CI contracts; Ruff/diff passed.
- Risk signals: cross-module CI/packaging, Linux container execution, configured-only live Docker evidence, DONE_WITH_CONCERNS
- Review findings: Important -- the folded exact-one wheel assertion does not terminate on multiple matches; bootstrap pip failure skips the harness and leaves no bounded `rc-smoke.json` artifact.
- Fix strategy: focused RED shell-contract tests; use explicit terminating wheel assertions; on bootstrap failure write the fixed bounded clean-wheel failure JSON from Python 3.11 stdlib and exit nonzero.
- Fix commit: `00ad211`; focused RED 2 failed/2 passed, GREEN 8 passed; shell cardinality and fallback JSON directly executed; Ruff/diff passed.
- Review result: Spec passed; no Critical, Important, or Minor findings. Both original findings closed. Live Docker remains an explicitly configured-only verification item for Task 4.
- Requirements artifact: `.superpowers/sdd/task-2-brief.md`
- Decision: packaging invokes the harness with `sys.executable`; the fixed `python:3.11-slim` non-root container is the minimum-version Linux evidence.

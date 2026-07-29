# M28 Subagent Progress

- Plan task: Task 1: RC harness 合同与离线入口
- OpenSpec tasks: 1.1, 1.2, 2.1, 2.2
- Phase: done
- Review mode: thorough
- Review/fix round: 2/2 plus user-preauthorized completion correction
- Base commit: a148c6132c0ede5abeeadec750fa214106ba97da
- Implementer: DONE_WITH_CONCERNS
- Implementation commit: 9586c70
- Risk signals: cross-module, security, concurrency, diff > 200 lines, DONE_WITH_CONCERNS
- RED/GREEN evidence: metadata cycle RED FileNotFoundError -> GREEN 11 passed; entrypoint cycle RED 9 missing-interface failures -> GREEN 9 passed; parent failure cycle RED 3 -> GREEN 3 plus false-pass RED 1 -> GREEN; final 174 passed, Ruff check/format passed
- Changed files: scripts/m28_release_candidate_smoke.py; tests/test_m28_release_candidate_smoke.py
- Review findings: Original three findings and contradictory check states are closed. Final re-review found the success predicate still omits fixed `version`, `python`, and exact top-level key validation, allowing a malformed zero-exit report.
- Fix strategy: completed through `2eaab53`; success now requires the exact report field set, version, supported Python value, digest, and six passed checks. Controller performed two final contract reviews with no remaining Task 1 finding.
- Latest RED/GREEN: contradictory zero-exit report RED preserved downstream passed states; GREEN 1 passed, Task 1 25 passed, adjacent 177 passed, Ruff check/format and diff check passed.

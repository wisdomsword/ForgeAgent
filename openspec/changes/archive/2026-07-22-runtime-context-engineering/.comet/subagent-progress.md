# M17 Subagent Progress

- Plan task: Task 9 complete: Prompt-cache/长任务验收、文档与全量验证已交付
- OpenSpec mapping: 5.1 stable prompt order; 6.1 long replay; 6.2 docs; 6.3 final matrix (coordinator checkoff only after fresh verification)
- Phase: done
- Base commit: 1b45384aaf9340e5301a913b3d40e4dd903aa530
- Implementation commits: d6fb69f; cdb1f8c; aa846db (final stale fixture repair)
- Changed files: tests/test_mock_replay_e2e.py; README.md; docs/model-client-contract.md; docs/m10-usage-observability-and-tools.md; docs/http-task-service.md; docs/threat-model.md
- TDD/characterization: replay fixture calibration exercised both fail-fast paths; final stable-prefix and long-replay tests passed without production changes
- Verification: full pytest 1351 passed, 11 skipped outside managed sandbox; Ruff passed; offline golden 20/20; OpenSpec strict valid; diff check passed; durable report updated
- Diff size: 229 insertions, 6 deletions
- Review mode: standard
- Risk review triggered: yes
- Risk signals: end-to-end long replay; prompt cache ordering; multi-document public contract; full repository verification
- Review/fix round: 1/1 complete
- Review result: final re-review PASS / APPROVED
- Open findings: none (0 Critical / 0 Important / 0 Minor)

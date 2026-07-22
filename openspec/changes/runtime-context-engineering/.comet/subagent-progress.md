# M17 Subagent Progress

- Plan task: Task 3 complete: Task/Step policy 装配与本地失败时序已交付
- OpenSpec mapping: 2.2 policy Task->Step/request boundary（直接）；2.3 窗口失败、完整交互、provider error 语义（完成后勾选）
- Phase: done
- Base commit: d397a2084bceb198db0fdadd4c4e45fd31953c0d
- Implementation commits: 6c98da693f2bd8a0df5bfe3f1e311f1a3a032149; fd774b1
- Changed files: src/forgeagent/task.py; src/forgeagent/step.py; tests/test_task.py; tests/test_step.py
- TDD RED: focused policy wiring -> 6 expected constructor TypeErrors
- TDD GREEN: initial focused -> 7 passed; fix regression -> 1 passed immediately (test-only coverage); Task/Step/streaming -> 101 passed; Ruff/diff check passed
- Review mode: standard
- Risk review triggered: yes (跨 Task/Step 模块并影响 LLM audit 边界)
- Risk signals: cross-module; public constructor compatibility; audit ordering; 4 changed files
- Verification note: full pytest produced no terminal summary and is not counted; final verification must rerun it
- Review/fix round: 1/1
- Review result: spec FAIL; quality CHANGES_REQUESTED
- Review result: re-review spec PASS; quality APPROVED; original Important closed
- Open findings: none

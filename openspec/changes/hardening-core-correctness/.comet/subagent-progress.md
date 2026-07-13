# Subagent Progress

- Change: `hardening-core-correctness`
- Plan: `docs/superpowers/plans/2026-07-13-hardening-core-correctness.md`
- Review mode: `thorough`
- TDD mode: `tdd`

## Current Task

- Plan task: `Task 1: 隔离测试 HOME 并稳定环境能力断言`
- OpenSpec mappings:
  - `1.2 为 CLI/MCP 测试提供隔离 HOME 或配置根目录 fixture，证明真实 ~/.forgeagent/mcp.yaml 不影响测试结果`
  - `1.3 审核本地监听权限和进程计数相关测试，改为能力探测或稳定断言，并保留对真实资源泄漏的检测`
  - `1.4 记录当前静态检查、隔离全量测试、Docker/网络可用性和已知环境限制，作为实施前基线`
- Stage: `done`
- Base commit: `736d4a0`
- Implementer: `019f5a92-89a8-7271-836e-9ad97d8697c8` (`Boyle`)
- Implementer report: `.superpowers/sdd/task-1-report.md`
- Reviewer: `019f5aa8-2d03-7ae2-a9a1-afee64477015` (`Dirac`)
- Review package: `.superpowers/sdd/review-736d4a0..b7699c1.diff`
- Re-reviewer: `019f5ab4-2922-7022-99ea-7c03f71974c8` (`Pauli`)
- Re-review package: `.superpowers/sdd/review-736d4a0..260fcfa.diff`
- Review/fix round: `2/2`
- Implementation commit: `b7699c1`
- RED evidence: HOME path regression observed real `/Users/admin/.forgeagent/mcp.yaml`; PID lifecycle regression raised `FileNotFoundError`; bind capability regression propagated `PermissionError`.
- GREEN evidence: focused MCP/CLI `78 passed, 1 skipped`; Ruff `All checks passed!`; full pytest `444 passed, 13 skipped`.
- Changed files: `tests/conftest.py`, `tests/mcp_fixture_server.py`, `tests/test_mcp_manager.py`, `tests/test_ssrf_guard.py`
- Risk signals: security-sensitive user configuration, subprocess lifecycle/shared state, cross-module test coordination.
- Review result: approved after fix. The lifecycle cleanup Important is resolved. The fresh re-review accepted the plan-mandated `PermissionError/OSError` behavior and left one non-blocking Minor: the HOME regression is less mutation-sensitive on CI hosts without a real user MCP config. Accepted for now because the hook implementation and import timing are directly verified; final whole-branch review must revisit it.
- Fix stage: `final-fix`
- Fix round: `1/2`
- Fix agent: `019f5aab-f3bf-7710-8688-3b6de0ca6867` (`Pasteur`)
- Fix commit: `260fcfa`
- Fix evidence: RED probe retained fixture PID and live manager thread after simulated post-startup exception; GREEN focused leak test `1 passed`, MCP/CLI `78 passed, 1 skipped`, Ruff passed.

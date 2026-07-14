# Subagent Progress

- Change: `hardening-core-correctness`
- Plan: `docs/superpowers/plans/2026-07-13-hardening-core-correctness.md`
- Review mode: `thorough`
- TDD mode: `tdd`

## Completed Task 1

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

## Completed Task 2

- Plan task: `Task 2: 禁用环境代理并约束重定向`
- OpenSpec mappings:
  - `2.1 增加大小写环境代理变量下 WebFetch 和 /search 必须直连的测试，并覆盖代理指向回环目标的绕过场景`
  - `2.2 让受保护的 URL opener 显式禁用环境代理，同时复用现有目标解析、地址分类和逐跳重定向校验`
  - `2.3 补齐私网、回环、链路本地、NAT64 和公网页面重定向到私网的回归覆盖`
  - `2.4 文档化 ForgeAgent 专用显式代理的未来契约与“本里程碑不实现代理转发”的边界`
- Stage: `done`
- Base commit: `faa7b2e`
- Implementer: `019f5aba-5787-74b2-9f86-572797b18a8e` (`Lorentz`)
- Implementation commit: `22178fc`
- RED evidence: pre-change SSRF suite `9 failed, 28 passed, 2 skipped`; proxy bypass and missing redirect handler failures observed.
- GREEN evidence: focused SSRF `37 passed, 2 skipped`; combined network suite `68 passed, 2 skipped`; full pytest `456 passed, 13 skipped`; Ruff clean.
- Changed files: `src/forgeagent/ssrf_guard.py`, `tests/test_ssrf_guard.py`
- Risk signals: security-sensitive network input and environment proxy handling; local bind/network capability skips.
- Review result: approved after fix. The final re-review found no Critical, Important, or Minor issues; effective redirected loopback rejection is proven offline for 301/302/303/307/308.
- Review/fix round: `1/2`
- Implementer report: `.superpowers/sdd/task-2-report.md`
- Reviewer: `019f5ad0-aa25-7722-816a-d1124f885845` (`Avicenna`)
- Review package: `.superpowers/sdd/review-faa7b2e..22178fc.diff`
- Fix stage: `final-fix`
- Fix round: `1/2`
- Fix agent: `019f5ad8-a466-7651-9f2b-866c1764d384` (`Ramanujan`)
- Fix commit: `acaa25f`
- Fix evidence: mutation RED `5 failed` across 301/302/303/307/308 by reaching the socket sentinel with an unguarded hop-2 handler; GREEN `5 passed`; combined network `73 passed, 2 skipped`; full pytest `461 passed, 13 skipped`; Ruff clean.
- Re-reviewer: `019f5ae9-6bd9-7d62-8976-d4a74c4446d6` (`Linnaeus`)
- Re-review package: `.superpowers/sdd/review-faa7b2e..acaa25f.diff`
- Review/fix round: `2/2`

## Superseded Task 3 Checkpoint

- Original plan task: `Task 3: 统一且最小披露的工具确认`
- Implementation commits: `a370811`, `72a1585`, `5894316`, `66612f6`
- Final focused evidence: Task 3 suite `113 passed`; full pytest `484 passed, 13 skipped`; Ruff clean.
- Final review result: blocked after two review-fix rounds because percent-encoded hostname values were not decoded before known-secret masking.
- Scope decision: user expanded the current change to include post-confirmation WebFetch and file outcome hardening. The approved design was committed through `7c3e13f`; the implementation plan was split into Task 3A/3B/3C and committed as `d356d6d`.

## Completed Task 3A

- Plan task: `Task 3A: 完成 confirmer URL 组件脱敏`
- OpenSpec mappings:
  - `3.1 为 MCP、WebFetch、FileWrite 参数分别增加 confirmer 格式化与批准/拒绝测试`
  - `3.2 扩展现有 confirmer 使其类型安全地支持三类工具参数，不引入新的审批框架`
  - `3.3 按 TTY 能力为 REPL 和单次 run 自动注入 confirmer，验证非 TTY 默认拒绝且 --interactive 仍只控制 Survey`
  - Partial: `3.6 为 percent-encoded/大小写变化/重叠的 hostname secret、encoded delimiter、IPv6/zone-id、组件级 mask 交互、Unicode content character count、WebFetch guard/network 失败和 FileWrite 成功/写入失败结果增加泄漏回归测试`
- Stage: `done`
- Base commit: `d356d6d`
- Implementer: `019f5f0c-8751-7613-84ea-81728735f025` (`Singer`)
- Implementer report: `.superpowers/sdd/task-3A-report.md`
- Implementer status: `DONE_WITH_CONCERNS`; implementation and verification completed, while the coordinator created the commit because the subagent sandbox could not write linked-worktree Git metadata.
- Implementation commit: `a8dc6c6`
- RED evidence: `UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_cli.py -q` exited 1 with `8 failed, 83 passed` before production edits.
- GREEN evidence: focused CLI `91 passed`; confirmer regression `123 passed`; Ruff `All checks passed!`.
- Changed files: `src/forgeagent/cli.py`, `tests/test_cli.py`
- Risk signals: security-sensitive URL/secret disclosure; `DONE_WITH_CONCERNS` due linked-worktree Git integration.
- Integration note: coordinator staged and committed only the implementer's two owned files after `git diff --check` passed; no source implementation was performed in the main session.
- Reviewer: `019f5f29-ac7a-7c22-9494-6113bd437e1b` (`Carver`)
- Review package: `.superpowers/sdd/review-d356d6d..a8dc6c6.diff`
- Review result: approved; no Critical or Important issues. The sole Minor was stale report commit state and was corrected in the ignored handoff report.
- Review/fix round: `0/2`
- Checkoff result: all five Task 3A plan steps and OpenSpec 3.1-3.3 passed exact-text `task-checkoff`; shared OpenSpec 3.6 remains pending until Task 3B/3C complete its remaining scenarios.

## Completed Task 3B

- Plan task: `Task 3B: 收敛 WebFetch 与 search 消费端异常`
- OpenSpec mappings:
  - Partial: `3.6 为 percent-encoded/大小写变化/重叠的 hostname secret、encoded delimiter、IPv6/zone-id、组件级 mask 交互、Unicode content character count、WebFetch guard/network 失败和 FileWrite 成功/写入失败结果增加泄漏回归测试`
  - Partial: `3.7 实施固定安全 WebFetch 失败消息与 FileWrite project-relative 成功/固定失败消息，并验证 Step feedback 不再暴露原始 URL、hostname 或宿主绝对路径`
  - Partial: `3.8 为 InvalidURL/BadStatusLine/LineTooLong/IncompleteRead/RemoteDisconnected、WebFetch artifact 写入、search 未知 charset、allowed_root="/"、非法路径及 FileRead/FileList 失败文本增加行为探针和回归测试`
  - Partial: `3.9 实施 WebFetch/search 消费端异常收敛、canonical commonpath 文件边界和 FileRead/FileList 固定失败消息，并验证 CLI outcome 渲染不泄漏敏感路径`
- Stage: `done`
- Base commit: `bf5faa6`
- Implementer: `019f5f30-c01c-76c3-ac2b-684a6d419dd2` (`Kierkegaard`)
- Implementer report: `.superpowers/sdd/task-3B-report.md`
- Implementer status: `DONE`
- Implementation commit: `d41d124`
- RED evidence: focused WebFetch/search/Step/CLI suite exited 1 with `19 failed, 156 passed` before production edits.
- GREEN evidence: same focused suite `175 passed`; scoped Ruff `All checks passed!`.
- Changed files: `src/forgeagent/tools.py`, `src/forgeagent/web_search.py`, `tests/test_web_file_tools.py`, `tests/test_web_search.py`, `tests/test_step.py`, `tests/test_cli.py`
- Risk signals: cross-module external-input/error-boundary change; security-sensitive URL/hostname disclosure; public ToolOutcome feedback contract.
- Reviewer: `019f5f38-cd09-70c3-93aa-2cb9361f8ee1` (`Confucius`)
- Review package: `.superpowers/sdd/review-bf5faa6..d41d124.diff`
- Review result: production behavior compliant; no Critical/Important. Minor test gap requires fix because the explicit plain `ValueError` branch was only indirectly represented by `InvalidURL`, an `HTTPException` subclass.
- Review/fix round: `1/2`
- Fix agent: `019f5f3c-4825-7fb2-b280-6ab34832ad1d` (`Halley`)
- Fix commit: `f372ce7`
- Fix evidence: mutation RED escaped plain `ValueError`; restored production then focused GREEN `1 passed`, Task 3B suite `176 passed`, Ruff passed.
- Re-reviewer: `019f5f40-2b7a-72d2-847e-3af6ce9d7909` (`Copernicus`)
- Re-review package: `.superpowers/sdd/review-bf5faa6..f372ce7.diff`
- Re-review result: approved with no Critical, Important, or Minor findings; direct plain `ValueError` coverage is mutation-sensitive and production restoration was verified.
- Review mode: `thorough`
- Checkoff result: all five Task 3B plan steps passed exact-text `task-checkoff`; shared OpenSpec 3.6-3.9 remain pending until Task 3C completes their file-boundary portions.

## Completed Task 3C

- Plan task: `Task 3C: 修复文件路径边界和失败披露`
- OpenSpec mappings:
  - Completion: `3.6 为 percent-encoded/大小写变化/重叠的 hostname secret、encoded delimiter、IPv6/zone-id、组件级 mask 交互、Unicode content character count、WebFetch guard/network 失败和 FileWrite 成功/写入失败结果增加泄漏回归测试`
  - Completion: `3.7 实施固定安全 WebFetch 失败消息与 FileWrite project-relative 成功/固定失败消息，并验证 Step feedback 不再暴露原始 URL、hostname 或宿主绝对路径`
  - Completion: `3.8 为 InvalidURL/BadStatusLine/LineTooLong/IncompleteRead/RemoteDisconnected、WebFetch artifact 写入、search 未知 charset、allowed_root="/"、非法路径及 FileRead/FileList 失败文本增加行为探针和回归测试`
  - Completion: `3.9 实施 WebFetch/search 消费端异常收敛、canonical commonpath 文件边界和 FileRead/FileList 固定失败消息，并验证 CLI outcome 渲染不泄漏敏感路径`
- Stage: `done`
- Base commit: `0287faa`
- Implementer: `019f5f47-5311-7803-836c-81ad5f51b913` (`Hubble`)
- Implementer report: `.superpowers/sdd/task-3C-report.md`
- Implementer status: `DONE`
- Implementation commit: `a97c3c0`
- RED evidence: focused file/restricted/Step/CLI suite exited 1 with `13 failed, 169 passed` before production edits.
- GREEN evidence: same focused suite `182 passed`; scoped Ruff `All checks passed!`.
- Changed files: `src/forgeagent/tools.py`, `src/forgeagent/_sandbox_worker.py`, `tests/test_web_file_tools.py`, `tests/test_restricted_backend.py`, `tests/test_step.py`, `tests/test_cli.py`
- Risk signals: security-sensitive path boundary, external input, duplicated containment semantics across host/restricted worker; documented concurrent ancestor-symlink TOCTOU residual.
- Reviewer: `019f5f50-3419-7782-aecc-eb1557c7afc0` (`Kepler`)
- Review package: `.superpowers/sdd/review-0287faa..a97c3c0.diff`
- Review result: implementation approved with no Critical/Important. Accepted Minor for repair: Step/CLI tests constructed already-sanitized outcomes instead of routing real FileRead/FileList failures through renderers.
- Review/fix round: `1/2`
- Fix agent: `019f5f55-33b3-79a2-9434-59ccbd2003d1` (`Nietzsche`)
- Fix commit: `2eeb946`
- Fix evidence: real FileRead/FileList outcomes routed through Step/CLI; mutation RED `2 failed`, focused GREEN `2 passed`, Task 3C suite `182 passed`, Ruff passed, production diff restored to empty.
- Integration note: subagent Git metadata permission failed; coordinator committed only the two test files after `git diff --check`, without source implementation.
- Re-reviewer: `019f5f61-cc08-7380-906c-5c2007d76380` (`Planck`)
- Re-review package: `.superpowers/sdd/review-0287faa..2eeb946.diff`
- Re-review result: approved with no Critical, Important, or Minor findings; real tool failures now exercise both renderer boundaries and no temporary production mutation remains.
- Review mode: `thorough`
- Checkoff result: all five Task 3C plan steps and OpenSpec 3.6-3.9 passed exact-text `task-checkoff`; the expanded core-correctness outcome scope is complete.

## Completed Task 4

- Plan task: `Task 4: 实施严格两阶段完成门控`
- OpenSpec mappings:
  - `3.4 增加工具成功、工具失败、解析错误与 completed: true 组合的 Step 状态转换测试`
  - `3.5 实施严格两阶段完成门控，只有后续无工具、无解析错误的独立响应可完成任务`
- Stage: `done`
- Base commit: `6c62ac4`
- Implementer: `019f5f6b-3548-71f1-993a-3fb5a23aba35` (`Gauss`)
- Implementer report: `.superpowers/sdd/task-4-report.md`
- Implementer status: `DONE`
- Implementation commit: `be4ff12`
- RED evidence: Step/Task suite exited 1 with `4 failed, 41 passed` for successful tool, failed tool, parse-error, and max-round completion bypasses.
- GREEN evidence: Step/Task/replay suite `49 passed`; scoped Ruff `All checks passed!`.
- Changed files: `src/forgeagent/step.py`, `tests/test_step.py`, `tests/test_task.py`
- Risk signals: shared Step state-machine semantics and public task termination contract.
- Failed reviewer: `019f5f7a-bece-7ee1-8ef8-764faa33ab72` (`Descartes`) was closed after remaining unresponsive and returning no verdict; this did not consume a review-fix round.
- Reviewer: `019f5f87-a2cb-7ce2-b0f8-db79fd9e5763` (`Mill`)
- Review package: `.superpowers/sdd/review-6c62ac4..be4ff12.diff`
- Review result: approved with no Critical, Important, or Minor findings.
- Review/fix round: `0/2`
- Review mode: `thorough`
- Checkoff result: all four Task 4 plan steps and OpenSpec 3.4-3.5 passed exact-text `task-checkoff`.

## Current Task

- Plan task: `Task 5: 增加 MCP required 启动语义`
- OpenSpec mappings:
  - `4.1 在 MCP 服务配置模型中增加默认 false 的 required 字段及兼容性解析测试`
  - `4.2 实施可选服务连接失败降级，验证失败服务工具被排除且诊断包含服务名和原因`
  - `4.3 实施必需服务连接失败的启动中止、资源清理和 CLI 非零退出测试`
- Stage: `done`
- Base commit: `3c67b17`
- Implementer: `019f5f90-80ad-7e43-bd77-2e8821841c2a` (`Einstein`)
- Implementer report: `.superpowers/sdd/task-5-report.md`
- Implementer status: `DONE`
- Implementation commit: `687ed24`
- RED evidence: MCP/CLI suite exited 1 with `6 failed, 112 passed, 1 skipped` for missing required config/query/startup abort.
- GREEN evidence: MCP/CLI `118 passed, 1 skipped`; MCP/CLI/tools regression `134 passed, 1 skipped`; scoped Ruff passed.
- Changed files: `src/forgeagent/mcp_manager.py`, `src/forgeagent/cli.py`, `src/forgeagent/res/mcp.yaml`, `tests/test_mcp_manager.py`, `tests/test_cli.py`
- Risk signals: public MCP configuration/startup contract, subprocess cleanup dependency, cross-module CLI integration.
- Reviewer: `019f5fa1-78eb-7140-98fe-d692f859d17a` (`Meitner`)
- Review package: `.superpowers/sdd/review-3c67b17..687ed24.diff`
- Review result: changes requested. Important: close failure can replace required startup error before Task 6; required failure status can carry unmasked exception secret text.
- Review/fix round: `1/2`
- Fix agent: `019f5fac-0309-7a01-9e82-03b948bd6d8b` (`Dalton`)
- Fix commit: `290acb2`
- Fix evidence: focused RED `2 failed, 2 passed`; GREEN `4 passed`; Task 5 regression `138 passed, 1 skipped`; Ruff passed. Exception-only cleanup containment and status masking implemented.
- Re-reviewer: `019f5fb4-1ff3-7be3-a7c7-296f30f5fd8b` (`Averroes`)
- Re-review package: `.superpowers/sdd/review-3c67b17..290acb2.diff`
- Re-review result: approved with no Critical, Important, or Minor findings.
- Review mode: `thorough`
- Checkoff result: all five Task 5 plan steps and OpenSpec 4.1-4.3 passed exact-text `task-checkoff`.

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
- Deferred OpenSpec mapping: `2.4` remains pending for Task 10's release-facing enterprise-proxy migration documentation.
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

## Completed Task 5

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

## Superseded Task 6 Checkpoint

- Plan task: `Task 6: 让 MCP close 使用绝对 deadline 且不抛异常`
- OpenSpec mappings:
  - `4.4 为正常关闭、无响应子进程、部分关闭失败、重复 close、daemon thread join 超时 warning 和延迟停止后的二次清理建立确定性测试并确定有证据的超时上限`
  - `4.5 使 MCPManager.close() 有界且幂等，为 loop thread 设置固定名称，在 manager 保存 shutdown future，由 loop coroutine 独占 holder wait/cancel 且只移除 done entries，future 超时时使用只读 fallback 并保留全部 pending 资源引用，允许重复 close 仅重试 cancel/stop/join，并保证关闭错误不覆盖任务结果或原始启动错误`
- Stage: `blocked`
- Base commit: `da5185b`
- Implementer: `019f5fbe-30ec-7263-9eff-354d79fb1ba1` (`Peirce`)
- Implementer report: `.superpowers/sdd/task-6-report.md`
- Implementer status: `DONE`
- Implementation commit: `541b300`
- RED evidence: focused close suite `8 failed, 22 deselected`; missing timeout constructors/thread name and real fixture cleanup cases.
- GREEN evidence: focused close `8 passed`; MCP+CLI `129 passed, 1 skipped`; fixture PID cleanup `2 passed` with both PIDs gone; Ruff check/format clean; no pending-task/runtime warnings.
- Changed files: `src/forgeagent/mcp_manager.py`, `tests/test_mcp_manager.py`, `tests/mcp_fixture_server.py`
- Risk signals: concurrency/shared mutable state, subprocess lifecycle, security-sensitive diagnostics, diff over 200 lines, residual hard-stuck daemon resources.
- Implementer concern: injected shutdown budgets at or below five seconds use a half-budget graceful phase to avoid an observed Future/coroutine absolute-deadline race; default budget retains the approved five-second graceful phase.
- Reviewer: `019f5fd9-1042-7fe1-8d11-7e6a86e4ca95` (`Hume`)
- Review package: `.superpowers/sdd/review-da5185b..541b300.diff`
- Review result: changes requested. Critical cancellation-vs-stop race can clear pending holders after thread stops; Important partial-init unawaited coroutine leak and fake hard-stuck probe; Minor scheduler-sensitive timing assertion. Short-budget split accepted.
- Review/fix round: `1/2`
- Fix agent: `019f5fe4-9a06-71d3-824f-1ee2f9761f87` (`Herschel`)
- Fix commit: `78a17bf`
- Fix evidence: real loop blocker and partial-init REDs; warning-as-error close `15 passed`; MCP+CLI `139 passed, 1 skipped`; full suite `560 passed, 13 skipped`; PID fixture `2 passed` with both PIDs gone; Ruff and diff checks clean.
- Fix scope: production changed only `src/forgeagent/mcp_manager.py`; tests changed only `tests/test_mcp_manager.py`; cancellation drain now precedes loop stop and dead/stopped-loop submission is guarded.
- Re-reviewer: `019f601a-78ae-70a0-82b1-2dae2aaf9aa1` (`Erdos`)
- Re-review package: `.superpowers/sdd/review-da5185b..78a17bf.diff`
- Re-review result: changes requested. Important: disable pops holder before await so close can miss in-progress cleanup; partial Thread.start success can leak unpublished live loop. Minor: graceful-vs-cancel test records indistinguishable values.
- Review/fix round: `2/2`
- Second fix agent: `019f6025-3c04-7db0-8075-b6b0c4b1a01e` (`Laplace`)
- Second fix commit: `cd36e31`
- Second fix evidence before final self-review: lifecycle `25 passed`; MCP+CLI `142 passed, 1 skipped`; full suite `563 passed, 13 skipped`; PID fixture passed with no survivors; Ruff/diff checks passed.
- Final self-review result: `BLOCKED` before controller re-review. Two new real regressions were added but remain uncommitted because they fail against `cd36e31`.
- Blocking regressions:
  - Re-enable after a timed-out `disable()` does not start/retain the replacement holder after old-holder cleanup.
  - `KeyboardInterrupt`/`SystemExit` while releasing the publication gate can leave `forgeagent-mcp-loop` alive and `_started=True`.
- Controller reproduction: `UV_CACHE_DIR=/tmp/forgeagent-uv-cache uv run pytest tests/test_mcp_manager.py::test_connect_interrupt_releasing_publication_gate_stops_running_loop tests/test_mcp_manager.py::test_enable_during_timed_out_disable_restarts_after_old_holder_cleanup -q -W error::RuntimeWarning` -> `3 failed`.
- Uncommitted evidence file: `tests/test_mcp_manager.py` contains only the two failing regressions above; no production file is uncommitted.
- Stop condition: maximum `thorough` review-fix budget exhausted. Do not dispatch another fix or advance to Task 7 without a new user decision.
- Review mode: `thorough`

## Approved Task 6 Structural Redesign

- User decision: approved Scheme A, replacing another narrow patch with loop-owned reconcile plus generation tokens; focused redesign is authorized within the existing change.
- Initial redesign commit: `20409b6` (`docs: redesign MCP lifecycle ownership`).
- Stage at this checkpoint: `design-update`; source implementation remained paused until the revised written design was approved and the Task 6 implementation plan was rewritten.
- Preserved RED evidence: the two uncommitted `tests/test_mcp_manager.py` regressions above remain unchanged and failing against `cd36e31`.
- OpenSpec mapping: pending tasks `4.4`, `4.5`, `4.6`; total change task count remains 38.
- Structural contract: loop-owned `(generation, task, stop)` holder slots, `(generation, session)` session slots, independent `restart_after_generation`, exact-generation publish/finalize/call handling, closing barrier and loop-owned snapshot.
- Facade contract: enable/disable/connect waiters are cancellable and do not own holder cleanup; disable shields the holder so a caller timeout cannot leave an untracked lifecycle waiter or cancel teardown.
- Startup contract: all initial holders start before the first await, ready waits share one monotonic deadline, the publication worker observes cancellation even when gate release fails before set, and post-publication primary control exceptions preserve identity through cleanup.
- Shutdown contract: the public absolute deadline bounds caller wait, while the unique shielded drain may continue finalizers; ordinary cleanup failures are isolated, and an incomplete authoritative task waits for a repeated-close retry signal instead of ending or duplicating.
- Disclosure contract: optional/required public MCP status and pending-name diagnostics expose only fixed categories/types with secret-value masking, never raw exception/config/server text.
- Newly confirmed audit gaps repaired in the written design: stale main-thread ClientSession selection; lost enable during unavailable finalization or after its slot is gone; teardown/restart-intent conflation; sequential N-times connection timeout and ready-timeout overwrite; holder task creation partial state; pending lifecycle waiter at loop stop; gate-before-set worker stranding; background-drain/deadline contradiction; cancelled first facade leaving repeated close no wait path; and done-incomplete shutdown dead-end.
- Next gate: strict OpenSpec/diff validation, then user approval of the final written spec. Only after approval may `writing-plans` reset Task 6 and implementation/review budgets.
- Post-audit RED revalidation: focused command still reports `3 failed in 1.06s`; the two gate-release parameter cases leave `_started=True`, and timed-out disable still fails to start replacement. No assertion was removed or relaxed.

## Task 6 Implementation Resume

- User authorization: proceed automatically after design repair; no further proposal/design/plan approval pause is required for this change. Continue through implementation, tests, final review and repair loops until verified complete.
- Rewritten plan: Task 6 is split into `6A` generation-safe holder/session ownership, `6B` transactional startup and lifecycle waiters, and `6C` one loop-owned absolute-deadline shutdown drain.
- Plan self-review: OpenSpec `4.4-4.6` map to `6A-6C`; all 38 tasks remain represented; placeholder and type/signature scans are clean.
- Execution mode remains subagent-driven, TDD, thorough review. The two preserved failing regressions are the first RED evidence and must not be weakened.

### Task 6A Complete

- Implementation commits: `d7ebecd` generation-safe ownership; `819074e` structured outer-timeout fix.
- GREEN evidence: `tests/test_mcp_manager.py` -> `52 passed, 1 skipped`; preserved regressions -> `3 passed`; Ruff check/format and diff check clean.
- Review result: approved after one fix round. Accepted Important: outer facade timeout escaped `call_tool()`; fixed without caller-thread session invalidation. Rejected scope expansion: fixed raw MCP call messages are not required because the approved design preserves the existing masked MCP outcome contract.
- Deferred by design to 6B/6C: shared ready deadline, cancel-aware lifecycle waiters, gate-before-set rollback, public status sanitization, and unique shielded shutdown drain.

### Task 6B Implementation Complete

- Scope: transactional publication-gated startup, shared initial ready deadline, cancel-aware
  synchronous lifecycle waiters, fixed public MCP status diagnostics, and fixed CLI mapping for
  ordinary manager startup infrastructure failures.
- RED evidence: focused Task 6B matrix reported `14 failed` before production changes, covering
  waiter cancellation, gate-before-set cleanup, post-publication cleanup, all-disabled retry,
  shared ready deadline/race, status disclosure, and CLI startup mapping.
- GREEN evidence: `tests/test_mcp_manager.py tests/test_cli.py` reported
  `168 passed, 1 skipped`; scoped Ruff reported `All checks passed`.
- Plan correction: Task 6B now lists `src/forgeagent/cli.py`, which is required to map an ordinary
  `connect()` infrastructure exception to a fixed `MCPStartupError` after bounded cleanup.
- Review status: independent thorough review pending before commit and Task 6C.

### Task 6B/6C Review Repair History

- Stage: `task-review`
- Review mode: `thorough`; structural redesign review/fix budget reset by the approved Scheme A decision.
- Current implementation files: `src/forgeagent/mcp_manager.py`, `src/forgeagent/cli.py`, `tests/test_mcp_manager.py`, `tests/test_cli.py`.
- Existing GREEN evidence before this repair: MCP focused `81 passed, 1 skipped`; MCP+CLI `183 passed, 1 skipped`; scoped Ruff check passed.
- Independent review findings accepted for TDD repair:
  - dead loop/thread state must not synthesize `_shutdown_complete` from empty maps or a missing/done shutdown task;
  - every `_start_holders()` allocation must recheck the closing barrier;
  - lifecycle `cancel()` ordinary exceptions must be isolated;
  - tool calls require matching state, holder and session generation;
  - active-generation call failure must set `tearing_down_generation`;
  - close-overlap and stop-before-cancel tests must prove ordering rather than eventual state;
  - completion published during join must be consumed by the same `close()`;
  - cleanup `CancelledError` must not replace a primary startup error while new `KeyboardInterrupt`/`SystemExit` still propagate;
  - deadline tests must verify exact facade/join timeout arguments and use a meaningful wall-clock bound.
- Required RED/GREEN files are restricted to the four current implementation files above. The worker must not modify docs, `ACTION_PLAN.md`, OpenSpec tasks or this checkpoint.
- Fix implementer: `019f616c-7925-7c10-ab92-86920c1f69c9` (`Ampere`).
- Fix commit: `c0a877d` (`fix: close MCP lifecycle review gaps`).
- RED evidence: targeted 13-test review matrix produced `12 failed, 5 passed`; failures covered lifecycle cancel isolation, close barrier allocation, dead-thread synthetic completion, join-time completion, loop-close evidence loss, generation mismatch calls, teardown generation and cleanup `CancelledError` replacement.
- GREEN evidence: targeted matrix `17 passed`; focused MCP/CLI after formatting `197 passed, 1 skipped`; scoped Ruff passed; `git diff --check` passed.
- Changed files: `src/forgeagent/mcp_manager.py`, `src/forgeagent/cli.py`, `tests/test_mcp_manager.py`, `tests/test_cli.py`.
- Risk signals: concurrency/shared mutable state, event-loop/thread lifecycle, public startup/close behavior, diff over 200 lines.
- Coordinator verification after `c0a877d`: full pytest `618 passed, 13 skipped`; full Ruff lint passed. Repository-wide format check exposed 16 historical/current formatting differences, so the plan now uses a base-ref-aware changed-file format gate and keeps unchanged baseline debt out of scope.
- Review result: changes requested. Three Important findings are real: caller-thread synthetic shutdown completion after facade submission rejection; non-atomic close-vs-holder allocation leaving an untracked task; startup rollback discarding a stopped loop when `loop.close()` fails. One Minor finding requires fixed-type logging for non-control CLI cleanup `BaseException`.
- Design/spec/plan repair commit: `1a6230a` (`docs: tighten MCP lifecycle ownership gates`). Strict OpenSpec validation and `git diff --check` passed. The repaired contract adds a minimal no-await lifecycle barrier, forbids caller-thread completion inference, retains stopped-loop rollback evidence, and makes the final format gate base-ref-aware.
- Review/fix round after approved structural reset: `1/2`.
- Current fix implementer: `019f6190-f838-7192-8df8-23a966828bd2` (`Wegener`), TDD, limited to MCP manager/CLI and their tests.
- Fix commit: `c1c88fd` (`fix: close MCP lifecycle race gaps`).
- RED evidence: new matrix `5 failed, 1 passed`; failures reproduced startup rollback evidence loss, caller-thread synthetic completion, close-vs-task allocation partial ownership, and both CLI cleanup logging omissions.
- GREEN evidence: new matrix `6 passed`; MCP+CLI `202 passed, 1 skipped`; scoped Ruff/format and diff checks passed.
- Coordinator verification: full warnings-as-errors pytest `623 passed, 13 skipped in 14.25s`; repository-wide Ruff lint passed; all five Task 6-owned Python files are formatted.
- Fresh re-reviewer: `019f619e-59a9-7713-83c5-c71691305c2e` (`Popper`). The implementer's own review was not used as the thorough review gate.
- Popper review result: changes requested. Important: ordinary shutdown facade submission failure followed by fallback `KeyboardInterrupt`/`SystemExit` was logged and swallowed.
- Second structural fix implementer: `019f61a6-179a-7b43-bf58-26d6d78c1578` (`Gibbs`).
- Fix commit: `8dc62c5` (`fix: preserve MCP fallback control exceptions`).
- Fix evidence: reverse-combination RED `2 failed`; targeted GREEN `4 passed`; `tests/test_mcp_manager.py -W error` `97 passed, 1 skipped`; Ruff/diff checks passed.
- Final independent reviewer: `019f6358-57fc-7d53-b695-f4a32e84c803` (`Bernoulli`).
- Final review result: changes requested. Accepted findings: the sibling facade-coroutine cleanup, lifecycle `_submit()` cleanup and startup rollback still swallowed process-control exceptions behind ordinary primaries; done-finalizer registration and no-auto-replacement after active call failure lacked mutation-sensitive tests. Rejected finding: SDK-raised control exceptions inside a background holder remain deliberate fixed server-failure isolation because direct asyncio Task propagation would terminate the loop thread without safely signalling the caller.
- Repair state at this checkpoint: Gibbs resumed with TDD ownership limited to `src/forgeagent/mcp_manager.py` and `tests/test_mcp_manager.py`; caller-thread exception precedence and both mutation gaps still required closure before Task 6 checkoff.

## Completed Task 3E

- Plan task: `Task 3E: 阻断 WebFetch artifact 静态 symlink 逃逸`
- OpenSpec mapping: `3.11` complete.
- Stage: `done`.
- Initial implementation: `22a9410` (`fix: contain WebFetch artifact paths`).
- Initial RED/GREEN: symlink escape changed the outside file and produced `1 failed, 43 passed`; restored implementation produced `44 passed`, Step/CLI regression `188 passed`, full suite `627 passed, 13 skipped`, scoped Ruff/format/diff checks passed.
- Fresh reviewer: `019f6358-5795-7502-911c-dbd4808b3150` (`Schrodinger`).
- Review result: production behavior correct; one accepted Minor test gap. Existing tests did not kill mutants that discarded `_validate_path()`'s canonical return or removed save-stage `ValueError` handling.
- Repair implementer: `019f61a0-2fcb-7ac2-a76f-a2d405d69c97` (`Linnaeus`).
- Repair commit: `c28cafd`.
- Repair RED evidence: discard-return mutant failed on missing canonical artifact; removed-`ValueError` mutant leaked its exception; a real unpaired-surrogate URL fragment escaped `UnicodeEncodeError` after a fake successful response.
- Repair GREEN evidence: targeted `3 passed`; WebFetch/File `47 passed`; Step/CLI regression `191 passed`; Ruff check/format and `git diff --check` passed.
- Final reviewer: `019f636b-4525-7ca3-b1d0-4023301aef44` (`Sartre`).
- Final review result: approved with no Critical, Important or Minor findings. Independent mutation rechecks failed as expected and restored focused suite reported `191 passed`.
- Changed files: `src/forgeagent/tools.py`, `tests/test_web_file_tools.py`.
- Residual risk: the documented hostile-host concurrent pathname-open TOCTOU remains; no platform-specific fd API was added.

## Completed Task 6

- Plan tasks: `6A`, `6B`, `6C`; OpenSpec mappings `1.1`, `4.4`, `4.5`, `4.6` complete. OpenSpec `1.1` is closed here because its proxy, generic-confirmer, same-round-completion and MCP-close RED evidence is now complete across Tasks 2, 3A, 4 and 6.
- Stage: `done` after the user-approved structural generation/loop-owned redesign and repeated independent review.
- Core implementation commits after the redesign: `d7ebecd`, `819074e`, `c0a877d`, `c1c88fd`, `8dc62c5`, `c425a2c`, `7accf0c`, `31c6172`, and `9e711e5` plus the earlier shutdown foundation commits recorded above.
- Final caller-control repair: `c425a2c` unified ordinary-primary/control-cleanup precedence; a real-loop probe then proved direct control raises from loop tasks killed `run_forever()`. `7accf0c` transports lifecycle controls as private results to the synchronous caller and isolates holder/finalizer controls as fixed unavailable state. RED showed thread death, wrong `TimeoutError`, and unretrieved warnings; GREEN real-loop matrix preserved exact identity and loop usability.
- Final SDK-call repair: `31c6172` isolates `KeyboardInterrupt`/`SystemExit` raised by `session.call_tool()` as type-only structured current-generation failure, preserves `CancelledError`, tears down the exact holder without implicit restart, and leaves the loop alive. Independent reviewer `019f63b2-f224-7653-8585-322acc954e48` (`Chandrasekhar`) approved with no findings.
- CLI integration: `0492b4d` returns before constructing a manager for all-disabled config and renders fixed masked Rich-literal pending output for `/mcp` timeouts. Reviewer `019f6397-49b6-7102-91c9-d0098e43f859` (`Darwin`) approved. Holistic reviewer `019f63c0-a812-7ba1-823a-f3bef863318b` (`Hegel`) then found real `enable()` swallowed its timeout; `9e711e5` removed that swallow and added real blocked-loop manager/CLI integration tests. Final reviewer `019f63e1-b1e9-7eb3-ad2b-651f5dc21435` (`Franklin`) approved with no findings.
- Final coordinator evidence: MCP+CLI `257 passed, 1 skipped`; full suite `682 passed, 13 skipped`; both ran with `RuntimeWarning` and `PytestUnraisableExceptionWarning` promoted to errors. Repository Ruff lint passed; all seven Task 6-owned Python files passed format check; strict OpenSpec validation and `git diff --check` passed.
- Skip evidence: one explicitly slow historical MCP hang test; ten Docker capability skips; one local bind capability skip; one outbound-network capability skip.
- Residual risk: a synchronously hard-stuck daemon loop may temporarily retain transport/FD/child-process resources after the public deadline; references and sanitized warning remain for bounded repeated close, as documented. No Python thread force-kill is claimed.

## Completed Task 3D

- Plan task: `Task 3D: 收口 CLI 确认通道与 M9 命令迁移`.
- OpenSpec mapping: `3.10`.
- Stage: `done`.
- Base commit: `331b830`.
- Dispatch checkpoint commit: `a494c78`; coordinator-only documentation commits advanced the shared branch while implementation ran, so the isolated implementation review range is the implementation commit's parent `7dcac1c` through `a48d487`.
- Implementer: `019f63ef-7254-7fd0-8103-118aab16fedb` (`Kuhn`).
- Implementer report: `.superpowers/sdd/task-3D-report.md`.
- Implementation commit: `a48d487`.
- RED evidence: initial CLI run `6 failed, 118 passed`; expanded secret/literal matrix `16 failed, 118 passed`.
- GREEN evidence: CLI `134 passed`; CLI/tools/WebFetch regression `197 passed`; scoped Ruff check/format and `git diff --check` passed.
- Changed files: `src/forgeagent/cli.py`, `tests/test_cli.py`.
- Reviewer: `019f63f9-9e36-7fa2-8722-496e5465631b` (`Archimedes`).
- Review result: changes requested. Important: the non-TTY REPL integration test covered only WebFetch, discarded its `TaskOutcome`, did not assert the fixed no-channel detail, and omitted FileWrite plus non-auto-approved MCP.
- Review mode: `thorough`; review/fix round: `1/2`.
- Fix agent: `019f63fd-c27e-7c41-9fba-72c25e33361e` (`Rawls`).
- Fix commit: `81d8c8f` (`test: cover non-interactive REPL tool rejection`).
- Fix RED evidence: with a temporary non-TTY confirmer mutation, the three new real REPL/Task/Tool cases failed `3 failed, 133 deselected`; `src/forgeagent/cli.py` was then restored to zero diff.
- Fix GREEN evidence: focused matrix `3 passed, 133 deselected`; CLI `136 passed`; CLI/tools/WebFetch regression `199 passed`; Ruff check/format and `git diff --check` passed.
- Fix scope: final commit changes only `tests/test_cli.py`; WebFetch, FileWrite and non-auto-approved MCP all assert the exact no-channel outcome, zero confirmation reads, next-goal continuation and no MCP call.
- Re-reviewer: `019f640c-48d1-7c33-8828-500450579b0c` (`Helmholtz`).
- Re-review result: approved with no Critical, Important or Minor findings. The reviewer confirmed the wrapper delegates to the captured real `run_once`, all three cases traverse Task/Step/Tool, and the fix range has no production diff.
- Checkoff result: all five Task 3D plan steps and OpenSpec `3.10` complete.
- TDD mode: `tdd`; RED and GREEN evidence are required before review.
- Allowed implementation files: `src/forgeagent/cli.py`, `tests/test_cli.py` only.
- Risk signals: security-sensitive external display/input handling and public REPL command-routing behavior. The implementer reported none, but the coordinator corrected that classification under the Comet risk checklist.

## Completed Task 7

- Plan task: `Task 7: 建立黄金 manifest、runner 和报告协议`.
- OpenSpec mappings: framework portions of `5.1`, `5.3`, `5.4`, and `5.5`; concrete 20-case completion remains with Tasks 8-9.
- Stage: `done`.
- Base commit: `8d5aed6`.
- Dispatch checkpoint commit: `d2795ec`; a coordinator-only Task 8 design correction advanced the shared branch before the implementation commit, so the isolated implementation range is `007c7ca..efd4777`.
- Implementer: `019f6413-fc16-7ed2-99fd-2360cabb5569` (`Kant`).
- Implementer report: `.superpowers/sdd/task-7-report.md`.
- Implementation commit: `efd4777`.
- RED evidence: runner test collection failed with `ModuleNotFoundError: No module named 'tests.golden'` before implementation.
- GREEN evidence: runner contract `22 passed`; coordinator rerun also `22 passed`; scoped Ruff check/format and `git diff --check` passed.
- Changed files: `.gitignore`, `tests/golden/__init__.py`, `tests/golden/manifest.py`, `tests/golden/cases.py`, `tests/golden/runner.py`, `tests/test_golden_runner.py`.
- Closed reviewer: `019f6421-4713-77b1-9c72-6b7d1f33b6e4` (`Russell`) remained running without a verdict after bounded waits and an interrupt request, so it was closed. No finding or review/fix round was recorded.
- Reviewer: `019f642c-58d3-7c61-bfe8-de38930149a9` (`Bacon`).
- Review result: changes requested. Important: `GoldenEvidence` subclasses are accepted by `isinstance`; a non-string `detail` can pass suite validation then crash Markdown rendering; the atomic overwrite test does not prove `os.replace` or same-directory temporary-file use.
- Coordinator audit additions: offline HOME isolation currently ends before report writing instead of after suite/report completion, and the standalone hostile-MCP test only imports `mcp_manager` without calling `load_mcp_config()`, so it does not prove the hostile file was not selected. Both require mutation-sensitive repair in the same fix round.
- Manifest audit addition: G43/G58/G59/G324 titles are mapped to unrelated capabilities, which would make the human report contradict the catalog despite correct IDs; the titles and the `cases.py` Tasks 8-9 ownership docstring require correction and a focused mapping regression.
- Review/fix round: `1/2`.
- Fix agent: `019f6430-6c02-76e3-93d9-ee4db222ccd0` (`Faraday`).
- Fix commit: `8a3ea38` (`fix: validate golden scenario result types`).
- Fix RED evidence: exact wrapper/detail tests produced `2 failed, 23 passed`; expanded isolation/config/title matrix produced `5 failed, 23 passed`; direct-write atomic mutant produced `1 failed, 27 deselected` before restoration.
- Fix GREEN evidence: runner contract `28 passed`; coordinator rerun also `28 passed`; scoped Ruff check/format and `git diff --check` passed.
- Fix scope: `tests/golden/runner.py`, `tests/test_golden_runner.py`, `tests/golden/manifest.py`, and `tests/golden/cases.py`; no product source or concrete Task 8-9 case was added.
- Re-reviewer: `019f6437-15c1-7ad2-880c-fdb6798d9ac7` (`Carson`).
- Re-review result: one accepted Important test gap: no test directly observes `run_suite()` executing under isolated HOME. One proposed Important was rejected: `test_offline_main_restores_home_variables_after_normal_and_runner_failure` proves `main()` invokes `_load_offline_configuration_modules`, while `test_offline_configuration_preflight_loads_mcp_config_without_constructing_manager` proves that helper invokes `load_mcp_config`; removing either edge fails its corresponding test.
- Stage at this checkpoint: `final-fix`; review/fix round: `2/2`.
- Second fix agent: `019f643a-cddd-7340-9f2c-316b350fdb93` (`Dewey`).
- Second fix commit: `71a8f9d` (`test: prove golden suite runs in isolated home`).
- Second fix RED evidence: moving the offline suite call outside isolation made the new integration test fail `1 failed, 28 deselected`; `tests/golden/runner.py` was restored to zero diff.
- Second fix GREEN evidence: focused test `1 passed, 28 deselected`; runner contract `29 passed`; coordinator rerun also `29 passed`; Ruff check/format and `git diff --check` passed.
- Final re-reviewer: `019f6441-2546-7691-b7fe-1eff0d698655` (`Boyle`).
- Final re-review result: approved with no Critical, Important or Minor findings; focused suite-isolation test independently passed.
- Checkoff mapping: all five Task 7 plan steps plus OpenSpec `5.1` and `5.3` complete. OpenSpec `5.2`, `5.4`, and `5.5` remain pending for Tasks 8-9.
- Review mode: `thorough`.
- TDD mode: `tdd`; RED and GREEN evidence are required before review.
- Allowed implementation files: `.gitignore`, `tests/golden/__init__.py`, `tests/golden/manifest.py`, `tests/golden/cases.py`, `tests/golden/runner.py`, `tests/test_golden_runner.py` only.
- Risk signals: public test-runner CLI/report contract, environment/configuration isolation, filesystem output containment, and an 833-line task diff. The implementer only called out pending case behavior; the coordinator retains the full Comet risk classification.

## Task 8 Detailed History

- Plan task: `Task 8: 实现 10 项通用黄金任务和 5 项真实模型入口`.
- OpenSpec mappings: common-case portion of `5.2` and real-callable portion of `5.4`; final completion remains pending until Task 9 and the full offline integration gate.
- Stage: `implementing`.
- Base commit: `4719efe`.
- Review mode: `thorough`; review/fix round: `0/2`.
- TDD mode: `tdd`; RED and GREEN evidence are required before review.
- Allowed implementation files: `tests/golden/cases.py`, `tests/golden/manifest.py`, `tests/test_mock_replay_e2e.py`, `tests/test_golden_runner.py` only.
- Risk signals: machine-judged acceptance logic, shared offline/real fixtures, restricted subprocess execution, mutation-resistant Edit/state/test-hash assertions, and an expected diff over 200 lines.
- Coordinator design correction: `abf3448` strengthens G05 from a use marker alone to a random alternate-state causal replay; strict OpenSpec validation passed.
- Implementation commit: `bc50e55` (`test: implement trusted golden task core`).
- Implementer report: `.superpowers/sdd/task-8-report.md`; focused GREEN `54 passed`; standalone runner `10 passed / 10 pending`, expected exit `1`; Ruff check/format and diff check passed.
- Coordinator verification before review: focused Task 8 `54 passed`; mutation-focused G05/G08/G15/G27/real-preflight `7 passed`; full pytest with RuntimeWarning promoted to failure `748 passed, 13 skipped`; full Ruff passed.
- Reviewer: `019f645e-3308-7d93-b9e9-f18c35e873f8` (`Newton`).
- Review result: changes requested. Accepted findings: G05 lacks a derived-output sink marker; G15/G27 do not bind exact Edit arguments; G27 does not bind the final successful Exec to `target`; G13 does not prove failed feedback reaches the next client request; G08 lacks a post-assertion witness and subprocess timeout; G01/G43 accept wrong JSON scalar types; real preflight does not check environment after `main()` returns.
- Review adjudication: the suggested one-probe conditional example is addressed with taint propagation from `+8` to the actual stdout sink, not with source heuristics or unbounded extra probes. This retains the random counterfactual and rejects conversion/branch/dead-add hard-coded output.
- Stage: `fixing`; review/fix round: `1/2`.
- Fix agent: `019f6467-e5e4-7741-9e3f-6878ff3ca2a2` (`Ptolemy`).
- Fix commit: `4e345ba` (`fix: harden golden scenario judges`).
- Fix RED/GREEN evidence: focused new regressions `9 failed, 1 passed` before repair and `10 passed` after; Task 8 `63 passed`; relevant suite `154 passed`; implementer full suite `757 passed, 13 skipped`; Ruff check/format and diff check passed.
- Coordinator verification: Task 8 `63 passed`; full pytest with RuntimeWarning promoted to failure `757 passed, 13 skipped`; standalone runner remains `10 passed / 10 pending`, expected exit `1`.
- Re-reviewer: `019f6472-fced-7322-8a8a-2a44aded19f6` (`Lovelace`).
- Re-review result: changes requested. Important: recorder remained directly callable from model globals; G08 re-executed model-controlled source in an unrestricted subprocess and timeout did not own descendants. Minor: same-workdir replay restoration omitted directories/symlinks/metadata.
- Final-fix design decision: keep instrumentation tests-only but execute model code in a nested namespace whose recorder stays in a wrapper closure; run counterfactual replay in an independent temporary allowed root instead of snapshot/restore; execute G08 tests through RestrictedBackend so its scrubbed environment, audit policy and timeout own the entire test process.
- Stage: `final-fix`; review/fix round: `2/2`.
- Final-fix agent: `019f647f-3005-7770-bd6b-f52162b7a0a4` (`Raman`).
- Final-fix commit: `48de111` (`fix: isolate golden replay execution`).
- Final-fix RED/GREEN evidence: G05/G08 regressions RED against `e6edd65`; focused final fixes `10 passed`; Task 8 files `66 passed`; restricted backend suite `38 passed`; coordinator full pytest with RuntimeWarning as errors `760 passed, 13 skipped`; Ruff and diff check passed.
- Final reviewer: `019f6492-331b-7920-bf07-e321a72eff24` (`Huygens`).
- Final review result: approved with no Critical, Important or Minor findings. Residual: real-model requests intentionally not run; CodeGraph index is primary-worktree baseline and final source was read directly from this worktree.
- Task 8 checkoff: all six plan steps complete; OpenSpec `5.4` complete; `5.2` and `5.5` remain pending until Task 9 supplies all 20 offline cases and the ordinary pytest integration gate.

## Completed Task 8

- Plan task: `Task 8: 实现 10 项通用黄金任务和 5 项真实模型入口`.
- Implementation commits: `bc50e55`, `4e345ba`, `48de111`; documentation/plan hardening commits: `abf3448`, `c6146cf`, `e6edd65`.
- Evidence: 10 common cases and 5 real callables; standalone runner `20 total / 10 passed / 10 failed`, failed IDs exactly G06/G14/G58/G59/G324/G329/G330/G332/G333/G355, exit `1`; focused suite `66 passed`; full pytest `760 passed, 13 skipped`; full Ruff passed.
- Review history: one implementation review and two repair rounds; final reviewer Huygens approved with no findings.
- Scope note: all changes are tests/golden infrastructure and docs/progress; no product source changes in Task 8.

## Task 9 Detailed History

- Plan task: `Task 9: 实现 10 项加固边界黄金任务`.
- OpenSpec mappings: remaining portion of `5.2` and `5.5`.
- Stage: `implementing`.
- Base commit: `48de111`.
- Review mode: `thorough`; review/fix round: `0/2`.
- TDD mode: `tdd`; RED and GREEN evidence are required before review.
- Allowed implementation files: `tests/golden/cases.py`, `tests/golden/manifest.py`, `tests/test_golden_runner.py` only.
- Risk signals: sandbox/audit-hook behavior, SSRF/confirmation doubles, MCP subprocess lifecycle and real `/mcp` slash routing, full 20/20 ordinary pytest integration, and preservation of Task 8 anti-cheating judges.
- Implementer: `019f649d-8287-7f13-920c-400dd0921107` (`Mencius`).
- Implementation commit: `edbc097` (`test: cover hardened runtime boundaries in golden core`).
- RED/GREEN evidence: pending-case RED `3 failed`; golden suite `68 passed`; boundary suite `238 passed, 2 skipped`; coordinator full pytest with RuntimeWarning as errors `762 passed, 13 skipped`; standalone runner `20/20`, `100.0%`, exit `0`; Ruff and diff check passed.
- Reviewer: `019f64bb-b99f-7763-abf4-fbfa1ee4f4a1` (`Hilbert`).
- Review result: changes requested. Important: G06/G58 create fixed sibling fixtures outside runner TemporaryDirectory cleanup; G330 synthetic redirect bypasses guarded public first-hop resolution/connection. Minor: G355 excludes only `optional:echo`, not the complete unavailable tool-label set.
- Stage: `fixing`; review/fix round: `1/2`.
- Fix handoff note: first fix agent `019f64c9-5a9c-7c21-a511-8a1e43b24ca8` was closed unresponsive before edits; second agent `019f64d4-b0cc-7a23-a7b9-47a955e36a68` wrote RED and implementation but stopped on model capacity; continuation agent `019f64df-7bef-77a0-bcd2-5890e24af333` found the normal G355 label parser also included status prefixes; final continuation agent `019f64e9-403f-7fb3-87a9-f04ab5b0dc2c` (`Lagrange`) corrected and committed the combined fix. These infrastructure interruptions did not consume an additional review/fix round.
- Fix commit: `d6cfa82` (`fix: tighten boundary golden fixtures`).
- Fix evidence: cleanup/guard/tool-label focused `6 passed`; golden suite `74 passed`; boundary plus MCP suite `375 passed, 3 skipped`; standalone runner `20/20`, `100.0%`, exit `0`; coordinator full pytest with RuntimeWarning as errors `768 passed, 13 skipped`; Ruff, format and diff check passed.
- Re-reviewer: `019f64f1-1d92-7360-9363-10af93366fff` (`Bohr`).
- Re-review result: approved with no Critical, Important or Minor findings. Residual non-blocking risk: G14's 0.2-second timeout and G355's one-second PID reap poll may be sensitive to extreme host scheduling delays.
- Task 9 checkoff: all six plan steps and OpenSpec `5.2`/`5.5` complete.

## Completed Task 9

- Plan task: `Task 9: 实现 10 项加固边界黄金任务`.
- Implementation commits: `edbc097`, `d6cfa82`.
- Evidence: all 20 offline scenarios pass through real local product/test entrypoints; ordinary pytest integration and standalone runner both report `20 passed / 0 failed / 100.0%`; full pytest `768 passed, 13 skipped`; full Ruff passed.
- Review history: one implementation review and one repair round; Bohr approved the repair with no findings.
- Scope note: Task 9 changed only `tests/golden/cases.py` and `tests/test_golden_runner.py`; manifest IDs/titles and product source remained unchanged.

## Current Task 10

- Plan task: `Task 10: 同步协议、威胁模型和 ACTION_PLAN`.
- OpenSpec mappings: `2.4` and `6.1-6.5`.
- Stage: `implementing`.
- Base commit: `d6cfa82`.
- Review mode: `thorough`; review/fix round: `0/2`.
- TDD mode: documentation synchronization; runtime claims require executable evidence, exact commands and report values.
- Allowed files: Task 10 documentation list plus `ACTION_PLAN.md` and this progress file only.
- Preservation rule: retain the user's existing uncommitted M11/M12/table edits in `ACTION_PLAN.md`; add only the approved M13 hardening status and evidence without staging unrelated user hunks.

### Task 10 ACTION_PLAN Preservation Checkpoint

- `user_before_sha256`: `26e051af8e29fdbd887d5c849ba7f3f27acd9ed2e7feab1ef3effa4e83f15d8f`.
- `expected_after_sha256`: `64ab3ca0b0b12e341233332481a5c83189d840f9bdf5b3a1ee0a8ed741bc5a15`.
- `m13_index_blob`: `c6e7824cd95ae8104b7cba324771d1c8781b28da`.
- Exact M13 row: `| M13             | 核心正确性加固：环境代理显式禁用与逐跳 SSRF；统一工具确认与最小披露；严格两阶段完成；MCP required、generation-safe 生命周期与有界关闭；20 项可执行离线黄金核心（5 项真实模型 opt-in）；协议、威胁模型与 README 同步。                                                                                                                                                                                                                                                                 | Ruff；完整 pytest；20 项离线黄金核心 20/20；CodeGraph 调用面复审 | 三道独立评审：技术一致性、全分支代码、验收证据 |`.
- Working-tree proof: `/tmp/forgeagent-action-plan-expected-after.md` and `ACTION_PLAN.md` compare byte-for-byte equal; the user-before copy is `/tmp/forgeagent-action-plan-user-before.md`. `/tmp` paths are convenience evidence only; hashes and exact text above are authoritative after restart.
- Index proof: `git diff --cached -- ACTION_PLAN.md` contains only the second anonymous post-M10 placeholder becoming M13; the first anonymous `HTTP` row remains unchanged. The working tree remains `MM` because user M11/M12/table edits are intentionally not staged.

### Task 10/10A Review And Repair Checkpoint

- Stage: `done`; review mode `thorough`; review/fix round `2/2` complete; final re-review approved.
- Initial documentation commit: `ca12e38`; first reviewer `019f6516-9306-7713-a4eb-6501aec48c90` found current model-client, protocol and T1-T11 contracts were over-compressed and identified the live `supports_images` registry loss. Independent design reviewer `019f6516-93dd-7be1-981f-4d031a3202ed` found required-cleanup, non-completion terminal, catalog-count, migration-plan and TOCTOU inconsistencies.
- Review repair commits: `387b2cb` relative redirects; `7e9e74a` image capability propagation; `3a503f4` explicit false override test; `14f2d3e` runtime contract restoration; `03ad4e5` sandbox fact correction; `da6daad` plus `fe640c3` exact catalog/README gates; `c790d96` explicit non-completion terminal characterization; `8063b42` Design/OpenSpec/plan reconciliation.
- RED/GREEN highlights: relative redirect probe failed on empty scheme then Web/SSRF suite passed `109 passed, 2 skipped`; image mapping failed six built-ins plus custom entry then registry/client suite passed `88 passed`; heading-only catalog gate exposed the real mixed heading/table format, corrected suite passed `67 passed`; Step/Task characterization rerun passed `47 passed`; escape tests passed `16 passed`; strict OpenSpec and diff checks passed.
- Scope expansion is corrective, not a new capability: it restores declared M9 image support, standard HTTP relative redirect behavior and executable documentation invariants without adding dependencies, proxy forwarding, a package installer or new sandbox primitives.
- `ACTION_PLAN.md` worktree still matches `expected_after_sha256`; subagent path-scoped commits reset the M13-only index entry, so the coordinator must regenerate/reapply `m13_index_blob` immediately before the Task 10 checkpoint commit and re-prove the cached diff contains only M13.
- Second reviewer `019f653f-45e4-79d0-8953-b844dbcd03e7` found three Important gaps and no Critical/Minor: production golden preflight counted coverage references as definitions, `need_info` lacked same-round characterization evidence, and Task 11 still claimed 40 rather than 45 OpenSpec tasks. Coordinator independently found the same 40/45 drift before the verdict and repaired the coverage map.
- Final review/fix commits: `81dffab` narrows golden definition parsing and runner responsibility; `846d622` proves a same-round tool outcome or parse error is recorded before one-round `needs_info` termination; `e0546f9`/`e4863f9` report the actual masked UTF-8 WebFetch artifact byte length and mutation-sensitive evidence; `41a38d7` contains the `/search` unpaired-surrogate fixed-unavailable path plus the corrected required-CLI hard-stuck contract.
- Coordinator whole-scheme audit additionally corrected stale M10 claims about zero custom redirect tracking and opener assembly, corrected the required/optional `build_mcp_manager()` docstring, and removed the unreachable promise that a CLI required-startup failure exposes a later `close()` handle. The honest contract is: queued shutdown facade/fallback work retains state before the drain exists; a recovered loop creates or reuses the sole drain; direct callers that still hold a manager may retry close, while the CLI exposes no manager/global registry/atexit path.
- Consumer RED/GREEN evidence: `/search` unpaired surrogate raised `UnicodeEncodeError` before repair and then `20 passed`; WebFetch byte metadata failed against character counting and then the focused Web/File suite passed `48 passed`; final coordinator `/search` rerun passed `20 passed` with RuntimeWarning/unraisable promoted to errors. Strict OpenSpec and cached diff checks passed.
- Final pre-review coordinator matrix: scoped Ruff lint passed; all 12 changed Python files passed Ruff format check; SSRF/search/Web/File/model-registry/streaming/Step/Task/golden/escape tests passed `292 passed, 2 skipped` with RuntimeWarning and PytestUnraisableExceptionWarning promoted to errors. The skips are explicit local-bind and outbound-network capability limits. Strict OpenSpec and `git diff --check` passed.
- Shared-worktree commit boundary note: a worker commit temporarily combined the independently authored WebFetch spec and `/search` files, then a later worker branch-pointer race moved those commits out of the current ancestry while preserving their bytes in the index/worktree. No reset/restore/rebase was used. The coordinator froze workers, revalidated the exact six staged files and committed them as `41a38d7`; the current linear HEAD contains all intended content. Commit titles are not used as evidence for file ownership.
- Final reviewer `019f656e-7432-7cf3-b8eb-a493fb42d6e0` approved `51512f2..c200c66` with no Critical, Important or Minor findings. It confirmed golden definition/parser responsibility, all three explicit non-completion statuses, redirect/proxy/search/WebFetch contracts, image propagation, required-CLI queued-shutdown versus direct-manager retry semantics, exact 45-task mapping, and M13-only committed ACTION_PLAN change. The reviewer explicitly classified its verdict as static code/contract review; Task 11 remains responsible for fresh comprehensive commands.

## Completed Task 10/10A

- Candidate HEAD: `c200c66`.
- Plan checkoff: Task 10 steps 1-6 and Task 10A steps 1-6 complete.
- OpenSpec checkoff: `2.4`, `2.5`, `3.8`, `3.11`, `3.12`, `5.6`, `6.1-6.4`, `6.6`, and `6.7` complete. `6.5` and `7.1-7.5` remain for Task 11.
- Preserved user state: `ACTION_PLAN.md` worktree SHA-256 remains `64ab3ca0b0b12e341233332481a5c83189d840f9bdf5b3a1ee0a8ed741bc5a15`; only M13 was committed, while the pre-existing M11/M12/table worktree difference remains uncommitted.

## Current Task 11

- Stage: `review-fix`; candidate `9046ff7`; all prior Task 11 verification evidence is invalidated by accepted product/spec fixes and must be rerun from Step 1.
- Invalidated evidence: full Ruff passed; changed-file format passed after `9046ff7`; full-repo format diagnostic found eight unchanged baseline files; focused suite `501 passed, 3 skipped`; full suite `780 passed, 13 skipped`; offline golden exit 0 with `20/20` and `100.0%`; strict OpenSpec and diff checks passed; CodeGraph emitted the expected different-worktree warning and direct source confirmed callers.
- Technical reviewer `019f65df-339c-7843-bf55-4f558da5dd21` accepted three Important findings: real `connect()` infrastructure failure can consume a second CLI close budget; shutdown-future `cancel()` process control skips retry/join; Superpowers Design Doc wrongly assigns full G01-G380 validation to production runner.
- Whole-branch reviewer `019f65df-3403-76f1-8b52-0d5c26c9560c` accepted one Important finding: MCP discovery tool descriptions/names can carry inherited environment secrets into `tools_prompt()` and `/mcp` output.
- Approved minimal repair: mask discovery descriptions at catalog ingestion; exclude a tool whose name changes under known-secret masking rather than create a non-routable alias; skip the assembly-layer close only when `connect()` already marked the real manager closed; continue shutdown retry and stop/join before propagating the first cleanup control; restore runner-versus-pytest catalog responsibility in the Design Doc.
- Repair commit: `d2c4fb3` (`fix: harden MCP discovery and shutdown`). The code change is limited to `mcp_manager.py`, `cli.py` and their focused tests; the contract/document repair remains in the following coordinator documentation commit.
- Repair RED/GREEN: five new focused regressions failed before implementation; coordinator rerun passed `278 passed, 1 skipped` with `RuntimeWarning` and `PytestUnraisableExceptionWarning` promoted to errors. Scoped Ruff check passed, all four changed Python files were already formatted, strict OpenSpec validation passed, and `git diff --check` passed.
- Initial repair design review at `d2c4fb3`: discovery `input_schema` was retained because it was not rendered by `tools_prompt()` or `/mcp`; safe names remained byte-for-byte routing identities. The fourth final review later invalidated the schema assumption because `list_tools()` is itself public catalog output; the final policy is recorded below. The assembly layer still uses the real manager's closed state only to avoid duplicate cleanup after `connect()` has returned from its own bounded close; defensive test doubles that fail before publishing closed state receive one cleanup attempt.
- Stage: `verification-reset`; all earlier Task 11 comprehensive evidence and both final-review verdicts remain invalid. Restart Step 1 from the post-documentation candidate HEAD.
- Second technical reviewer `019f6635-e84b-7e12-8d03-f3a9ade4279b` and whole-branch reviewer `019f6636-3ffd-7553-b2a0-dae2c5df31e2` independently found the control-primary plus cancel-control branch skipped drain retry. The whole-branch reviewer additionally proved a secret-bearing configured server identity still reached prompt/status/CLI; the technical reviewer found the repeated-close Design Doc text incorrectly said to cancel the saved facade again.
- Accepted repair: exclude every tool belonging to a server whose routing identity changes under known-secret masking; return masked server identities from public status/required diagnostics while preserving raw internal state keys; independently run shutdown future cancel, drain retry and stop/join cleanup blocks and preserve the original control primary; remove the repeated-facade-cancel claim.
- Second repair RED/GREEN: four focused regressions failed before implementation (secret-bearing server catalog/status/CLI plus two control-primary combinations), then passed `4 passed`; a required-startup diagnostic consumer regression was added and the final focused set passed `5 passed`. The complete MCP/CLI pair passed `283 passed, 1 skipped` with warning gates enabled. All comprehensive Task 11 evidence and both second-round reviewer verdicts are invalidated until the repair and documentation are committed and Step 1-6 restart.
- Third technical reviewer `019f695c-cd49-7e50-aba0-ee50801f9d7f` and whole-branch reviewer `019f695d-793b-74d0-b4a8-27ae43a3a017` both found raw MCP identities still entered ToolOutcome feedback/CLI and that masked public dict keys could collide; the technical reviewer also found raw lifecycle log labels, while the whole-branch reviewer found repeated-close and `_stop_and_join()` control exceptions could skip later cleanup sites. Coordinator independently found the ToolOutcome/structured-call leak before their verdicts.
- Accepted structural repair: build a manager-owned stable raw-to-public server-label map that preserves safe raw names and adds deterministic non-secret suffixes to redacted collisions; share it across status, required diagnostics, CLI, ToolOutcome, call errors and logs while preserving raw internal routing. Split repeated retry/wait/stop-join and `_stop_and_join()` stop/join/state/identity/loop-close sites so the first control is propagated only after every still-valid bounded cleanup.
- Third repair RED/GREEN: eight focused regressions failed before implementation, then passed `8 passed`; the close control matrix expanded to 12 passing cases across retry, completion wait, loop stop, thread join, state check and loop close. Additional call-routing and collision-specific CLI consumers passed, and the final MCP/Tools/CLI/Step suite passed `357 passed, 1 skipped`; comprehensive Task 11 evidence and third-round reviewer verdicts remain invalid until this repair is committed and Step 1-6 restarts.
- Fourth technical reviewer `019f699a-bef3-7ae0-9bd6-0a0f1276f59c` and whole-branch reviewer `019f699b-9879-73c3-803c-e3fbe783e113` both found the top-level `close()` preflight thread-state control escaped before cleanup. The whole-branch reviewer additionally found raw known secrets could remain in public `MCPToolInfo.input_schema`. Coordinator independently identified the preflight gap before both verdicts.
- Accepted repair: conservatively treat a preflight control as live-thread state, continue first or repeated close, combine it with later cleanup using the existing first-control rule, and propagate only after drain/stop/join; recursively mask JSON-like schema string keys/values, reducing the public schema to `{}` on masked-key collision or non-JSON-like input.
- Fourth repair RED/GREEN: five regressions failed before implementation (one schema plus first/repeated preflight for both control classes), then passed `5 passed`; two additional schema-collision/non-JSON cases passed, and final MCP/Tools/CLI/Step passed `364 passed, 1 skipped`. All previous comprehensive evidence and fourth-round reviewer verdicts are invalid until this repair is committed and Step 1-6 restarts.

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

## Current Task 7

- Plan task: `Task 7: 建立黄金 manifest、runner 和报告协议`.
- OpenSpec mappings: framework portions of `5.1`, `5.3`, `5.4`, and `5.5`; concrete 20-case completion remains with Tasks 8-9.
- Stage: `task-review`.
- Base commit: `8d5aed6`.
- Dispatch checkpoint commit: `d2795ec`; a coordinator-only Task 8 design correction advanced the shared branch before the implementation commit, so the isolated implementation range is `007c7ca..efd4777`.
- Implementer: `019f6413-fc16-7ed2-99fd-2360cabb5569` (`Kant`).
- Implementer report: `.superpowers/sdd/task-7-report.md`.
- Implementation commit: `efd4777`.
- RED evidence: runner test collection failed with `ModuleNotFoundError: No module named 'tests.golden'` before implementation.
- GREEN evidence: runner contract `22 passed`; coordinator rerun also `22 passed`; scoped Ruff check/format and `git diff --check` passed.
- Changed files: `.gitignore`, `tests/golden/__init__.py`, `tests/golden/manifest.py`, `tests/golden/cases.py`, `tests/golden/runner.py`, `tests/test_golden_runner.py`.
- Closed reviewer: `019f6421-4713-77b1-9c72-6b7d1f33b6e4` (`Russell`) remained running without a verdict after bounded waits and an interrupt request, so it was closed. No finding or review/fix round was recorded.
- Review mode: `thorough`; review/fix round: `0/2`.
- TDD mode: `tdd`; RED and GREEN evidence are required before review.
- Allowed implementation files: `.gitignore`, `tests/golden/__init__.py`, `tests/golden/manifest.py`, `tests/golden/cases.py`, `tests/golden/runner.py`, `tests/test_golden_runner.py` only.
- Risk signals: public test-runner CLI/report contract, environment/configuration isolation, filesystem output containment, and an 833-line task diff. The implementer only called out pending case behavior; the coordinator retains the full Comet risk classification.

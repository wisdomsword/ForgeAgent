# M26 协作完成证据绑定验证报告

## 结论

正式验证 PASS，可进入归档。M26 的运行时实现、OpenSpec delta、技术设计、测试、文档和独立受控
证据一致；未发现未解决的 Critical 或 Important 正确性、安全、边界问题。mypy、M16 loopback
黑盒和 packaging 全依赖安装仍受工具/沙箱/离线缓存限制，均明确记录为未验证的环境补充项，
没有冒充通过，也不改变 M26 自身产品门禁结论。

## 记分卡

| 维度 | 状态 | 证据 |
|---|---|---|
| 完整性 | PASS | OpenSpec tasks 13/13、实施计划 20/20；产品与证据提交 `354592f` |
| 正确性 | PASS | delta spec 2 requirements、18 scenarios 均有实现或测试证据；最终聚焦回归 274 passed |
| 一致性 | PASS | proposal、design、技术设计、运行时、文档和 M26 evidence 均绑定当前 Task/attempt/snapshot |
| 安全 | PASS | 检查命令仍由宿主冻结；证据不进入模型 schema；审计不泄露命令、路径、输出或摘要 |
| 环境补证 | PARTIAL | 可执行全套和离线 build 通过；mypy/loopback/packaging 安装补充项受环境限制 |

## 新鲜验证证据

- 沙箱可执行全套：`2408 passed, 22 skipped in 99.00s`；排除必须绑定 loopback socket 的
  `tests/test_m16_filewrite_allowlist_blackbox.py` 与单独验证的 `tests/test_packaging.py`。
- M26 最终聚焦回归：`274 passed in 35.65s`，覆盖 check runner、协作工具/Runner/integration、
  M26 harness、M23/M25 历史锁、协作文档和持续验证合同。
- M26 harness：最终版本 `38 passed`；script/test SHA-256 分别为
  `b1fe8161028e352ad921271cfe184e896e4ad5f5b60255574350c24d569a1325` 与
  `b3337bb91b0dad3602f69841cc7ce9e4ef9c57dfd2ebfe1d40c5a3fa4d78d49d`。
- Ruff：全库 check 通过，113 files format check 通过；`git diff --check` 通过。
- 构建：复用本机已下载的官方 Hatchling/依赖缓存后，项目原始
  `UV_OFFLINE=1 uv build --offline` 成功生成 `forgeagent-0.1.0.tar.gz` 与
  `forgeagent-0.1.0-py3-none-any.whl`。
- OpenSpec strict：当前 change valid；全库 `21 passed, 0 failed`。
- 归档后复核：delta spec 已同步到主 `runtime-collaboration` spec；全库主规格
  `20 passed, 0 failed`，且没有残留 delta-only section 标题。
- M26 权威证据 `2026-07-28-final-v5`：`M26_EVALUATION_OK runs=4 execution=controlled`；
  Duo/Triad 各覆盖 skip-check-first 和 all-pass，4/4 completed；environment 绑定 harness 与
  `check_runner.py`/`collaboration.py` 源码 hash；`fallback_reason=provider_unavailable`。
- 历史隔离：相对 M26 planning base，`docs/evaluation/m23` 与 `docs/evaluation/m25` 无差异。
- 安全扫描：M26 的 `src`/`scripts` diff 未发现硬编码 key/token 模式。

## 需求与场景映射

- 实际检查输入摘要：`src/forgeagent/check_runner.py` 对与复制规则一致的普通文件树计算确定性
  digest，并在副本执行前后验证稳定性；`tests/test_check_runner.py` 覆盖稳定、忽略、变化和错误。
- 当前 Task 私有证据：`src/forgeagent/collaboration.py` 的 `_CheckEvidence` 仅在单次 evaluator
  registry 内共享，不进入持久状态 schema，也不进入模型参数 schema。
- 全通过门：`RunCheckTool` 保存宿主结果；`SubmitEvaluationTool` 要求每个冻结检查最新通过、
  attempt 相同、检查摘要相同且仍等于当前 Candidate。缺失、失败、超时、旧 attempt、混合摘要、
  检查后变化和 digest 错误均有工具测试。
- 恢复与新 attempt：Runner 集成测试证明重建 registry 后证据为空，旧通过证据不能复用。
- 兼容与提前拒绝：无检查 registry 精确保持既有集合；包含失败验收项的 verdict 不强制跑完检查。
- 审计：`collaboration.check` 只记录 check ID、任务/operation ID、attempt、状态和耗时，不记录
  argv、路径、输出、内容或 snapshot digest。
- 端到端证据：M26 harness 使用真实 Task/Step/CollaborationRunner/RunCheck/pytest 链，固定
  MockClient 只替代 provider 角色回复；它证明运行时门禁，不证明真实模型服从性。

## OpenSpec 与设计一致性

- proposal 的 false completion 目标已满足，未扩张到 M27 路由、single 模式或历史评测改写。
- `design.md` 的五项决策全部实现：Task 私有证据表、实际副本摘要、只约束全通过 verdict、恢复
  重跑和安全审计。
- 技术设计的数据流、错误分类、模型 schema 与持久状态边界均与实现一致。
- delta spec 的 2 个 modified requirements、18 个 scenarios 均能定位到实现和可执行测试；没有
  发现 delta spec 与 design doc 漂移。
- 关联技术设计文件存在且元数据指向当前 change。

## 代码审查与双重自审

- Task 1-3 thorough review 均无未解决 Critical/Important/Minor；Task 4 review 发现 fixture 路径
  逃逸、symlink、执行类型复用、provider 分类、schema/交叉一致性和临时文件安全问题，均补 RED、
  修复并复审通过。
- 第一轮最终自审按 proposal/spec/tasks/设计逐条映射，发现 M23 测试把历史不变性误扩张为未来
  全局字节锁，已收敛到 M23 自身提交区间并验证。
- 第二轮最终自审专查模糊、错误、过度保守、前后不一致、遗漏和 false completion 旁路；补齐
  运行时源码 hash 的严格映射校验、中间证据批次非权威标记及运行时合同文档。
- 最终独立复审确认 final-v5 与当前 harness、`check_runner.py`、`collaboration.py` hash 一致，
  无剩余 Critical 或 Important finding。

## 环境限制

- `mypy` 不在项目环境中；`uvx mypy src` 的沙箱网络失败，沙箱外请求被审批基础设施
  `403 model unsupported by selected groups` 拒绝。未新增依赖，未宣称类型检查通过。
- `tests/test_m16_filewrite_allowlist_blackbox.py` 在沙箱内为 `11 failed, 1 passed`；11 项均因
  `PermissionError` 无法分配 loopback port，未到达产品断言。
- `tests/test_packaging.py` 的两个纯合同测试通过；全 wheel 安装测试在离线缓存中缺少
  `mcp>=1.28.1`，无法完成依赖解析。项目原始离线 build 已独立通过。
- 上述沙箱外补证均按用户授权尝试，但审批基础设施仍返回 403；未绕过权限边界。

## 分支处理

- 当前分支：`feature/20260728/bind-collaboration-completion-evidence`。
- 两轮自审后选择 finishing-a-development-branch 方案 3：保留分支至 Comet archive 完成，再本地
  合并到 `main`，不 push。归档前不合并可避免 active change 生命周期跨分支漂移。
- `.superpowers/sdd/task-1-report.md` 是用户明确保留审查的无关修改，不属于 M26，所有提交继续排除；
  因该文件仍在 worktree 中，归档后也不强制删除 worktree 或分支，避免丢失用户数据。

## 最终评估

M26 满足正式 verify 的通过标准，可同步 delta spec 并归档。归档后更新 ACTION_PLAN、里程碑链接和
状态，提交归档产物，再将 feature 分支本地合并到 main；不 push。mypy、loopback 和 packaging
全依赖安装作为环境补证缺口保留，不影响本次已验证的 M26 完成证据绑定能力。

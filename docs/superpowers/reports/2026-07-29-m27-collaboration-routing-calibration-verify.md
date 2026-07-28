# M27 协作路由校准验证报告

## 结论

M27 的路由、M25 派生分析、Memory 文档、当前验证基线与 Linux evidence claim 已完成验证；
build-stage preparation/handoff 已完成，等待后续 Comet archive/branch gates。默认路由现在是
Single；显式 Single/Duo/Triad 优先；只有可信宿主已
绑定非空冻结检查时才自动 Triad。M25 冻结证据没有任务类别的 Triad solved rate 严格高于
Single，因此没有恢复自动类别。

本轮没有把环境限制冒充为产品通过：完整 pytest 在当前沙箱得到
`12 failed, 2325 passed, 22 skipped`，其中 11 项无法分配 loopback port，1 项无法在线解析隔离
构建依赖。排除这两个环境依赖测试文件后的当前沙箱可执行基线为
`2322 passed, 22 skipped`。复用既有官方依赖缓存的离线 wheel/sdist 构建、Golden、Ruff、
OpenSpec strict 与 diff 检查均通过。

## 验证记分卡

| 维度 | 状态 | 证据 |
| --- | --- | --- |
| 路由合同 | PASS | 最终路由/HTTP/文档/派生组合专项 `98 passed`；Single CLI/REPL route audit 独立复审通过 |
| M25 派生 | PASS | `M27_ROUTING_ANALYSIS_OK runs=270 restored=none`；派生/独立复算 `23 passed`；冻结输入无 diff |
| 文档合同 | PASS | M27 文档合同最终 `16 passed`，HTTP 边界合同 `128 passed` |
| 当前仓库 | PASS WITH ENVIRONMENT EXCEPTIONS | 沙箱可执行 `2322 passed, 22 skipped`；完整尝试的 12 项环境失败逐项保留 |
| 静态/规格/Golden | PASS | Ruff check；115 files format；OpenSpec `21/21`；Golden `20/20` |
| 发布构建 | PASS WITH INSTALL EXCEPTION | 离线 wheel/sdist 构建通过；全依赖 wheel 安装受离线解析限制未完成 |

## 新鲜命令与结果

### pytest

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q
```

结果：`12 failed, 2325 passed, 22 skipped in 114.16s`。

- 11 项失败位于 `tests/test_m16_filewrite_allowlist_blackbox.py`，共同原因为
  `PermissionError: [Errno 1] Operation not permitted`，脚本未能分配 loopback port：
  `test_blackbox_script_passes_exact_two_phase_contract`、
  `test_blackbox_script_reports_model_tool_drift_as_inconclusive`、
  `test_blackbox_script_rejects_forbidden_extra_tool_as_inconclusive`、
  `test_failed_extra_tool_does_not_override_filewrite_evidence`、
  `test_failed_extra_tool_with_artifact_remains_inconclusive`、
  `test_tool_drift_takes_precedence_over_wrong_allowlist_decision`、
  `test_allowed_phase_tool_drift_precedes_wrong_decision`、
  `test_blackbox_script_rejects_token_leak_in_denied_audit`、
  `test_blackbox_script_rejects_degraded_terminal_audit`、
  `test_blackbox_script_times_out_and_stops_queued_server`、
  `test_blackbox_script_reports_wrong_allowlist_decision_as_failure`。
- 1 项失败为 `tests/test_packaging.py::test_wheel_and_sdist_release_contents`，隔离
  `uv build` 无法从 PyPI 解析 Hatchling；DNS 在当前沙箱不可用。
- 非沙箱重跑按授权申请，但自动审批服务返回 `403 Forbidden`：所选 auto-review model group
  不支持当前模型。未以间接手段绕过权限边界。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  --ignore=tests/test_m16_filewrite_allowlist_blackbox.py \
  --ignore=tests/test_packaging.py
```

结果：`2322 passed, 22 skipped in 101.99s`。README 与 platform-support 使用这一“当前沙箱可执行
基线”，并紧邻记录完整尝试的 12 项环境失败。

### Ruff、OpenSpec、Golden、构建与 diff

```bash
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run ruff format --check .
openspec validate --all --strict
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run python -m tests.golden.runner \
  --output-dir /tmp/forgeagent-m27-golden
UV_CACHE_DIR=/tmp/forgeagent-m26-offline-cache-v3 UV_OFFLINE=1 \
  uv build --offline --out-dir /tmp/forgeagent-m27-build-offline-v2
git diff --check
```

结果：Ruff `All checks passed!`，`115 files already formatted`；OpenSpec
`21 passed, 0 failed`；Golden `20/20 passed (100.0%)`；离线构建生成
`forgeagent-0.1.0.tar.gz` 与 `forgeagent-0.1.0-py3-none-any.whl`；diff check 无输出。

packaging 测试单独复验为 `2 passed, 1 failed`：wheel/sdist 内容断言已通过，失败发生在新建 venv
安装 wheel 的依赖解析阶段。因此本报告只宣称构建产物生成与内容阶段通过，不宣称全依赖安装通过。

## M25 派生关键证据

- 冻结输入：270/270 terminal raw；protocol、environment、summary、原 report 与 raw tree 无 diff。
- baseline：Single/Triad solved rate 均为 `73.3%`；Triad 平均延迟 `144.486s` 对 Single
  `73.312s`，平均逻辑调用 `11.63` 对 `5.97`。
- bugfix：Single `85.0%`，Triad `45.0%`。
- feature：Single `20.0%`，Triad `5.0%`。
- refactor：Single `45.0%`，Triad `15.0%`。
- 误完成定义为 `runtime_completed == true && solved == false`；派生 JSON 同时保留 scheduled 与
  runtime-completed 两种分母，并按 raw `runtime_reason` 原样分类。
- M25 早于 M26 检查证据绑定；这些数据只用于否定无证据的自动升级，不证明当前 bound-check
  Triad 的质量。

## Delta spec 映射

- `runtime-collaboration`：默认 Single、显式模式优先、`bound_checks` 自动 Triad、candidate files
  不构成证据，均由 resolver 与入口测试覆盖。
- `collaboration-routing-evaluation`：冻结输入不可变、误完成双分母、终止原因原样、质量/延迟/
  调用成本与恢复裁决，均由脚本、机器投影、报告和合成篡改测试覆盖。
- `continuous-verification`：当前基线来自本轮命令；Linux verified 只覆盖 Pipeline 50 / Job 249
  runner topology；历史数字保持历史标签。

## 两轮最终自审

### 第一轮：需求与证据边界

- 确认没有恢复任何自动 Triad 类别；机器字段 `automatic_triad_restored_for` 为空。
- 确认 candidate file requirements 没有被当作 evidence；只有可信宿主的非空冻结检查事实产生
  `reason=bound_checks`。
- 确认 M25 protocol 与正式 run tree 无 diff，派生输出只位于独立 M27 目录。
- 确认 Memory 只是修正文档：runtime 准入后可原子持久化、用户可编辑；`--no-memory` 与
  `--no-identity` 边界未改变。
- 确认 Linux verified claim 没有推断未记录的 amd64/arm64 架构。

### 第二轮：兼容、歧义与遗漏

- 搜索 `programming task|override_required|needs_confirmation|MEMORY.*只读|Linux amd64/arm64|remains configured`。
  剩余 `needs_confirmation` 属于合法 Planner 计划确认状态；`override_required` 只保留稳定数据形状；
  `Linux amd64/arm64` 和 Memory 只读仅出现在历史设计或负向测试中。
- 显式 Single、Duo、Triad 均优先于宿主证据；`allow_weaker_override` 真/假不改变路由。
- HTTP 普通 options 与服务器 YAML 都拒绝 `has_bound_checks`；任务文本不能伪造该事实。
- HTTP 与 Loop 的 audit/checkpoint 投影继续保留稳定字段，普通入口默认 Single。

## 评审结论

Task 1-3 均经过 thorough review 与修复轮。确认问题包括：派生裁决字段与报告结论一致性、输出
发布回滚、README 中显式模式优先和可信宿主边界、HTTP/YAML 对 `has_bound_checks` 的严格拒绝。
这些问题均已增加失败测试、修复并复验。

Task 4 独立 review 另确认 2 项 Important 与 1 项 Minor，均属于收尾证据一致性而非产品代码：

- Important：`ACTION_PLAN.md` 的权威摘要和 M27 行仍写“进行中”，且没有写入实际
  `2322 passed, 22 skipped`、完整 12 项环境失败边界、OpenSpec `21/21`、Golden `20/20` 和
  离线 build 结果。现已改为“已完成，待 Comet 归档”并补齐全部证据。
- Important：OpenSpec 4.3/4.4 在独立 review 问题尚未修复、Comet archive/branch gate 尚未执行时
  提前混合完成边界。现 4.3 只在本轮修复和受影响复验后完成；4.4 改为后续归档、
  `milestones/latest` 与分支收尾任务并保持未勾选。
- Minor：Task 4 报告把已经存在的提交 `09ceb10` 写成“待执行”，且没有记录本轮 review fix。
  报告现按 Git 实际提交更新，不声称 active change 已归档。

提交 `4dc1537` 修复上述首轮 findings。复审继续发现状态机死锁与审查证据缺口：4.4 若等待实际
archive/branch finish 会阻塞 archive gate，若提前勾选又会越过用户决策门；同时仓库缺少独立、
受跟踪的 review 工件。本轮把 4.4 改为已完成的 build-stage preparation/handoff，并新增
[Task 4 独立审查记录](2026-07-29-m27-task4-independent-review.md)。该工件记录 reviewer 角色与范围、
首轮和复审 findings、`4dc1537` 修复及未重测边界，不虚构 agent ID。

Task 5 最终独立评审继续发现并修复两类 Important 产品缺陷：

- CLI/REPL 的普通 Single 分支没有发出 `collaboration.route`，使默认 Single 与显式
  `--mode single` 缺少稳定路由审计。现均在执行前只发出一次事件；测试同时断言事件不包含 goal、
  argv 或路径，且 Duo/Triad 不会重复审计。独立复审结论为 Approved。
- M25 派生输出在 backup/restore 的异常边界可能删除既有公开文件或继续破坏性探测。修复先后补齐
  RED/GREEN：只有 `lstat()` 的明确 `FileNotFoundError` 表示没有旧文件；backup/restore 的后置
  `FileNotFoundError` 视为状态不确定，停止该文件的后续破坏性操作、返回非零并保留固定事务目录
  证据；普通、状态明确的 I/O 失败仍完整回滚并清理。最终独立复审结论为 Approved。

最终发布合同不声称两个公开文件具有跨进程崩溃或文件系统故障下的不可见原子切换。正常成功时
两份输出都被替换并清理事务目录；普通可判定失败时恢复旧状态；异步中断、回滚不确定、清理失败或
探测状态不确定时不冒充成功，并保留恢复证据。`tests/test_m27_m25_routing_analysis.py` 与独立复算
共 `23 passed`，最终组合专项共 `98 passed`。

## 已知边界

- 当前沙箱不能绑定 loopback socket；M16 黑盒测试未在本轮环境完成。
- 当前网络被禁，隔离 packaging 安装无法解析全部依赖；离线 wheel/sdist 构建已通过。
- M25 是有限历史样本且早于 M26；未来若恢复某类自动 Triad，必须由新的冻结、版本化证据和
  独立 change 支撑。
- M25 派生输出事务不承诺进程被强制终止、文件系统损坏或外部并发改写时的跨文件原子性；这些情况
  通过非零退出和保留恢复证据收敛，而不是被计为成功。
- OpenSpec change 仍处于 active path；本报告不提前宣称已归档。
- delta spec 同步、最终归档状态和实际 branch finish 仍须经过后续 Comet gates。

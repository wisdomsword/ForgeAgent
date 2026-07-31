# M43 Executor Rewrite/Dependency Baseline 验证报告

- 变更：`measure-executor-rewrite-baseline`
- 里程碑：M43
- 日期：2026-07-31
- 验证模式：full
- 基线提交：`a14630ff8a730b98839289785e365bda0519381a`
- evidence 绑定提交：`47876661`
- 最终 verdict：`keep_python`

## 结论

M43 已使用标准库离线入口完成 Python trusted/restricted/container 执行路径的六项 Rewrite/Dependency
基线测量。两次同机复测均未达到预先固定的性能、可靠性或维护成本瓶颈阈值；兼容与回滚证据
ready，但 container 为 `not_available`、团队维护演练为 `not_ready`。当前证据只支持继续使用
Python，不授权 Rust 重写、新依赖、运行时切换或状态迁移。

## Verification Report: measure-executor-rewrite-baseline

| Dimension | Status |
| --- | --- |
| Completeness | 10/10 build/finalization tasks；4/4 requirements、9/9 scenarios 已有实现或验证映射 |
| Correctness | 六项指标、固定阈值、三态 backend evidence、故障恢复、no-replay 哨兵和 verdict 均有回归 |
| Coherence | runtime/dependency diff 为零；设计、delta spec、JSON evidence 与基线文档一致 |

### Issues by Priority

- CRITICAL：无。
- WARNING：container 本机离线条件不满足，保持 `not_available`；不得解释为通过。
- WARNING：`rustc/cargo` 存在但维护演练未运行，team capability 保持 `not_ready`。
- SUGGESTION：未来只有出现真实越阈、同机干净复测、团队能力和可回滚 verifier 后，才另立
  full Comet change 做单模块试验。

## 六项指标证据

| Metric | Status | 核心 evidence |
| --- | --- | --- |
| performance | `within_threshold` | 最终 trusted median `0.010625 ms`；restricted median `108.947834 ms`、`9.077731 ops/s` |
| reliability | `within_threshold` | trusted/restricted 均 20/20；crash/timeout 结构化失败后恢复；两个哨兵均证明失败 block 未重放 |
| maintenance cost | `within_threshold` | 目标运行时 750 行；直接运行时依赖 8 |
| compatibility | `ready` | `ExecResult` 五字段、三 backend、restricted state roundtrip 与 one-shot JSON protocol 保持 |
| team capability | `not_ready` | 工具存在不等于能力；build/debug/package/profiling/rollback 演练未运行 |
| migration/rollback risk | `ready` | M43 runtime/schema/config/data 变化均为 0，Python 路径保持 |

第一次同提交复测为 trusted `0.009959 ms`、restricted `109.946416 ms`、`9.185010 ops/s`；
第二次为上表最终值。两次 verdict 均为 `keep_python`，阈值没有因结果修改。

## 两轮自评与代码审查

- 第一轮检查 schema、状态词表、阈值先验性、fault recovery、secret/path 禁入和 verdict。发现未知
  metric status 会误落 `keep_python`、no-replay 是硬编码声明、team capability 漏 profiling 门；均先补
  RED 回归，再增加固定状态词表、故障哨兵和 profiling threshold。
- 第二轮检查 YAGNI、文件归因、运行时/依赖零变化、证据提交绑定和流程一致性。发现归档存在性测试
  与 verify-before-archive 形成循环，并发现 evidence commit 尚未包含测量器修复；前者改为 active/archive
  双位置追溯，后者先提交修复，再从 `47876661` 重跑并冻结 evidence。
- `requesting-code-review` 要求独立 reviewer；当前会话规则禁止创建子代理，因此没有伪造独立审查。
  使用 fresh `base-ref..HEAD` diff、直接测量输入归因、聚焦测试与安全扫描替代。未发现未处理的
  CRITICAL 或 IMPORTANT 问题。

## 验证证据

- TDD RED：未知 status、no-replay 可观察性、profiling threshold 共 `4 failed`，失败原因与缺口一致。
- TDD GREEN：对应 `4 passed`。
- M43/executor 聚焦：`68 passed, 10 skipped in 12.59s`。
- 预收敛整库回归：`2651 passed, 10 skipped, 2 deselected in 175.75s`；两条 deselected 是当时尚未
  生成的验证报告/里程碑追溯断言，不是产品或实现失败。
- 零排除全量 pytest：`2653 passed, 10 skipped in 173.67s`。
- `ruff check .`：通过。
- `ruff format --check .`：`141 files already formatted`。
- `git diff --check`：通过。
- `openspec validate --all --strict --no-interactive`：归档前 `33 passed, 0 failed`。
- 公开 evidence 的绝对路径、测试 secret 与常见凭据表达式扫描：无命中。
- `base-ref..HEAD` 对 `src/`、`pyproject.toml`、`uv.lock` 的 M43 提交差异：零。

零排除 pytest、全库静态门禁和归档前 OpenSpec 已通过。Comet full verify 通过；归档脚本 7/7
步骤成功，主规格已同步，change 已移动到
`openspec/changes/archive/2026-07-31-measure-executor-rewrite-baseline/` 并标记 `archived: true`。
归档后的全量 pytest、Ruff、format、diff check 与 OpenSpec strict 结果见本报告最终验证补记。

## 最终验证补记

- Comet full verify：tasks、verification、报告、语言和分支处理 5 项全部通过。
- Comet archive：`7/7 steps succeeded`，主规格无 delta-only 标题残留。
- 归档后聚焦：`26 passed in 1.55s`。
- 归档后零排除全量 pytest：`2653 passed, 10 skipped in 173.25s`。
- 归档后 Ruff：通过；format：`141 files already formatted`；diff check：通过；OpenSpec strict：
  `33 passed, 0 failed`。
- 首次归档后回归因评审文档改写破坏一条固定追溯短语，得到聚焦 `1 failed, 25 passed`、全量
  `1 failed, 2652 passed, 10 skipped`；恢复原短语并补充 M43 归档句后，上述聚焦和全量门禁均通过。

## 未执行与边界

未访问网络、未拉取镜像、未运行真实 container/Linux/Podman、未执行 Rust 构建或维护演练。
未执行 package upload、PyPI、tag 或发布自动化。普通开发分支已按用户明确授权推送，归档提交还会
在最终门禁通过后更新到同一分支；这只是版本控制交接，不代表恢复公开分发目标。

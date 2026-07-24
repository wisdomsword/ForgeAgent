---
change: eval-evaluator
status: passed
---

# M20 Eval-Evaluator 验证报告

## 结论

M20 的 10/10 项 OpenSpec 任务、7/7 项需求和 13/13 个规格场景均有实现与测试证据。
独立代码评审最初拒绝实现并提出 7 项问题，复审追加 2 项；全部按 TDD 修复后，最终
复审结论为 no findings、批准。change 已满足 build 与验证门禁，尚未执行真实模型
Evaluator，也尚未归档。

## 完整性

| 维度 | 结果 |
| --- | --- |
| Tasks | 10/10 完成 |
| Requirements | 7/7 已实现 |
| Scenarios | 13/13 有覆盖 |
| Design | OpenSpec design、Superpowers Design Doc 与实现一致 |

主要映射：

- `tests/golden/manifest.py`、baseline JSON 和 runner preflight 固定原有 20 项 ID、标题、
  顺序与真实模型 eligibility；应用代码不更新 baseline。
- `src/forgeagent/evaluation.py` 聚合严格有限的四项指标，消费固定 `task.outcome` 与
  `llm.outcome` 投影，原子写入 record/index，并只读取有界、安全 run ID 历史。
- `src/forgeagent/evaluator.py` 校验声明的相对 artifact，将声明文件复制到一次性 snapshot，
  使用仅含 FileRead/FileList 的独立 restricted Task，并严格解析有证据的 pass/fail YAML。
- `src/forgeagent/cli.py` 仅在显式 `evaluate` 分支延迟导入评估模块；普通 run、REPL、serve
  与 offline golden 不加载或调用 Evaluator。

## 验证证据

- M20 专项：`466 passed in 38.21s`。
- 最终完整回归：`1617 passed, 11 skipped in 85.91s`。其中 M16 环回端口和 packaging
  测试需要沙箱外执行；同一命令在具备所需能力的环境中退出 `0`。
- `uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m20-final-golden-verified`：
  `20/20 passed (100.0%)`。
- `uv run ruff format --check src tests`：`86 files already formatted`；
  `uv run ruff check src tests`：`All checks passed!`。
- `uv build --out-dir /tmp/forgeagent-m20-build-final`：sdist 与 wheel 均成功生成。
- `npx openspec validate eval-evaluator --strict`：`Change 'eval-evaluator' is valid`。
- `git diff --check`：通过。

## 三次评审

- 技术方案评审：对照 ACTION_PLAN M20、OpenSpec proposal/design/specs 和批准后的实现计划，
  未引入服务、数据库、依赖、HTTP endpoint、自动真实模型调用或 Generator/Evaluator 打回环。
- 代码评审：初审发现目录外删除、未声明 artifact 可读、round metrics 不可达、无证据通过、
  unsafe schema/path、普通 CLI 顶层依赖等 7 项；复审又发现 `task.outcome` 无 emitter 与趋势
  上限/无界扫描 2 项。全部修复并补回归后，最终独立复审批准、无剩余 finding。
- 验收评审：专项、完整回归、golden、Ruff、build、OpenSpec strict、diff check 全部通过；
  普通入口与原 20 项可信核心边界保持不变。

## 残余风险

- 未执行 credentialed real-model Evaluator；该入口按设计保持显式 opt-in，不是离线门禁。
- LLM 语义判断仍非确定，artifact prompt injection 仍可能影响意见；restricted 是应用层隔离。
- 源 artifact 在 snapshot 复制前存在同机并发修改窗口；复制时复核大小，后续只读 snapshot。

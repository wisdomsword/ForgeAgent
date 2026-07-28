# M25 编程模式质量—成本评估

M25 是独立于 M23 的描述性评估协议。固定范围为 9 个自包含任务（3 个 M23 基线、2 个
bugfix、2 个 feature、2 个 refactor）x 2 个模型 x 3 种模式 x 5 次重复，共 270 次串行真实
调用。模型固定为 `claude-haiku-4-5` 和 `gpt-5.4-mini`；模式为 Single、Duo、Triad。

- 协议：[`docs/evaluation/m25/protocol.json`](protocol.json)
- 机器汇总：[`summary.json`](runs/2026-07-27-haiku-4-5-gpt-5-4-mini/summary.json)
- 中立报告：[`docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md`](runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md)
- 独立复算：[`scripts/m25_independent_recompute.py`](../../../scripts/m25_independent_recompute.py)
- 验证报告：[`docs/superpowers/reports/2026-07-28-m25-programming-mode-evaluation-verify.md`](../../superpowers/reports/2026-07-28-m25-programming-mode-evaluation-verify.md)
- 归档 change：[`openspec/changes/archive/2026-07-28-m25-programming-mode-evaluation`](../../../openspec/changes/archive/2026-07-28-m25-programming-mode-evaluation/)

## 命令

以下命令会调用真实模型并产生费用；运行前必须配置协议中的两个模型路由和 credential：

```bash
uv run python scripts/m23_mode_evaluation.py run \
  --protocol docs/evaluation/m25/protocol.json \
  --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini

uv run python scripts/m23_mode_evaluation.py aggregate \
  --protocol docs/evaluation/m25/protocol.json \
  --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini

uv run python scripts/m25_independent_recompute.py \
  --protocol docs/evaluation/m25/protocol.json \
  --output docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini
```

本次证据为 270/270 份 terminal raw；独立复算输出
`INDEPENDENT_RECOMPUTE_OK runs=270`。raw、environment 和 summary 只保存安全投影，不保存
任务 prompt、模型回复、工具正文、credential、API key、provider base URL 或绝对工作区路径。

## 解释边界

结果只绑定记录的日期、本机 Darwin/arm64 环境和当时的 provider 路由；provider 侧模型权重
不能独立固定或验证。九个固定任务和五次重复仍是有限样本。本报告不自动排名 Single、Duo、
Triad，不建立跨模型排名，也不输出产品推荐。M23 的
`docs/evaluation/m23/protocol.json` 与正式历史证据没有修改；新增模型或任务必须建立新的版本化
change 和证据根，不能改写 M25。

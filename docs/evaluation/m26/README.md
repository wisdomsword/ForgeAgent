# M26 完成证据绑定评估

本目录只验证 M26 的协作完成门：Duo/Triad 在宿主注入冻结检查时，不能只靠 Evaluator
自报全通过完成；检查结果必须来自当前 Evaluator Task，并绑定当前 Generator attempt 与同一
Candidate 快照。M23/M25 的历史质量—成本证据不在本评估中改写或重分类。

## 固定协议

[`protocol.json`](protocol.json) 固定四个运行：Duo/Triad 各覆盖一次“先跳过检查提交全通过，
被拒绝后运行检查再提交”和一次“先运行检查再直接提交”。输出使用独立 M26 schema，只保存
安全投影、hash、结构化工具顺序与完成状态，不保存 prompt、模型回复、credential、base URL、
绝对路径、检查输出或 Candidate 内容。

## 权威证据

[`2026-07-28-final-v5`](runs/2026-07-28-final-v5/) 是当前权威批次：4/4 completed，执行类型为
`controlled`，`fallback_reason=provider_unavailable`。它使用真实 `Task`、`Step`、
`CollaborationRunner`、`RunCheck` 与 pytest 检查执行链，但角色回复由固定 `MockClient` 驱动；
environment 同时绑定 harness 与两份 M26 运行时源码 SHA-256。因此它证明该具体运行时版本的
门禁，不是 credentialed provider 或真实模型服从性证据。

`2026-07-28-controlled`、`2026-07-28-auto`、`2026-07-28-final-v2`、
`2026-07-28-final-v3` 和 `2026-07-28-final-v4` 是开发期中间批次，保留用于审计，不作为最终结论。空的失败尝试目录
不会形成 Git 证据。

## 复现

```bash
UV_CACHE_DIR=/tmp/forgeagent-m26-eval-cache uv run python \
  scripts/m26_completion_evidence_evaluation.py \
  --protocol docs/evaluation/m26/protocol.json \
  --output docs/evaluation/m26/runs/<new-run-id> \
  --execution auto
```

若 registry 或 provider 不可用，`auto` 会明确记录原因并退回受控执行；不会把受控结果伪装为
真实 provider 结果。已有 evidence 不会被覆盖，输出路径也不能逃逸 M26 根或指向 M23/M25。

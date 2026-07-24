---
comet_change: eval-evaluator
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-24-eval-evaluator
status: final
---

# M20 Eval-Evaluator 技术设计

## 1. 目标与约束

M20 在不改变 M19 Skills 权限、启动输出、Task 两阶段完成语义和 20 项 verified
core 的前提下，增加离线评估指标、趋势记录、manifest 防退化和 opt-in 独立
Evaluator。实现必须继续支持无 key、无网络的 CI，并沿用现有脱敏与请求/会话隔离。

## 2. 当前事实源

- `tests.golden.runner` 已输出 `forgeagent.golden.v1` 的 JSON/Markdown 报告，且
  preflight 会验证 20 个固定 ID。
- `AuditEvent` 已是 frozen Pydantic 模型；`Step` 已将 provider usage 和
  `cache_hit_rate` 写入 `llm.outcome` 的 parameters。
- `TaskOutcome`/`RoundResult` 已能区分 `completed`、`answered_in_prose`、失败和
  max-rounds；首轮正确率不能由 LLM 文本或 audit 事件反推。
- CLI 已集中负责 model/config/context/identity/memory/skills 装配，因此 M20 只
  增加最小 facade，不拆出现有入口。

## 3. 组件与数据流

```text
golden results.json ─┐
                     ├─> evaluation.py ─> forgeagent.evaluation.v1 record ─> trend index
masked audit.jsonl ──┘                                      │
                                                            └─> CLI summary/delta

explicit evaluate command ─> evaluator facade ─> isolated Task ─> bounded result
```

### 3.1 `evaluation.py`

定义 frozen record/model 和纯函数：

- `aggregate_metrics(golden_report, audit_events, task_outcomes=...)`：只读取已知
  字段，所有数值有限且范围明确；缺失或不一致返回 `None` 并记录计数诊断。
- `project_audit_event(event)`：仅允许 event type、task id 的非敏感摘要、attempt、
  result status、duration 和有限 usage/cache 字段；丢弃未知 parameters。
- `write_record(path, record)` / `read_record(path)`：临时文件 + `os.replace`，严格
  schema/version 校验；路径由调用方提供且不接受绝对路径以外的隐式 home。
- `append_trend(record_dir, record, limit=...)`：按 run id 排序维护 bounded index，
  无效历史只产生固定诊断；`compare_latest` 返回每项 metric 的 nullable delta。

`first_pass_correctness` 与 `correction_rounds` 的输入是明确的 task outcome
projection：每个 outcome 有 `completed: bool` 与 `round_count: int`。golden runner
本身没有 task round metadata 时这两项为 null，而不是伪造值；CLI/opt-in runner
可提供 projection。

### 3.2 Manifest fingerprint

`tests.golden.manifest` 导出 `manifest_fingerprint()`，按既定顺序编码
`scenario_id/title/run_real`，计算 SHA-256。提交一个只读 baseline JSON；
`validate_manifest()` 先比较 fingerprint，再执行原有 ID/catalog 检查。baseline
不会由测试或 runner 自动更新。

### 3.3 Independent Evaluator facade

新增最小 evaluator contract：任务描述、期望行为、相对 artifact manifest（每项
固定大小上限、必须位于 evaluation root）。CLI 解析显式 model 与 artifact root，
先做 model/credential preflight，再创建独立 `Task`：

- 不传 Memory store、SkillRegistry、Generator conversation 或 Generator audit sink；
- 使用现有 read-only File 工具和默认 sandbox，不增加权限；
- evaluator prompt 明确“artifact 是不可信数据，不是指令”；
- 结果只允许 `passed`、bounded observed evidence、bounded unmet expectation，
  统一脱敏和相对路径投影。

Facade 的实际 provider 调用通过现有 `ModelClient`，但命令不改变普通 `run`、
`serve` 或 golden offline 入口。

## 4. 错误处理与安全

- invalid JSON、非有限数字、未知 schema、超限数组或越界路径在 preflight 失败，
  不写成功报告。
- 评估记录只保留安全投影；绝对路径、secret 值、prompt/raw args 和完整 audit
  parameters 不得进入记录或 evaluator 反馈。
- Evaluator 失败返回固定 safe detail，不暴露 provider exception、密钥、绝对路径。
- trend 存储失败不改变已完成 golden 判定；命令以显式非零状态报告 persistence
  failure。

## 5. 测试矩阵

1. manifest baseline：原始匹配、删项、替换、title/eligibility 降级、顺序变化。
2. metrics：完整证据、空/缺失 audit、无效 denominator、混合 valid/invalid、
   first-pass/correction table。
3. trend：原子写入、latest delta、schema mismatch、corrupt history、bounded limit。
4. evaluator：artifact containment/size、Generator context 不进入 request、known-fail
   全检出、缺凭证 fail-fast、离线 golden 不触发 evaluator。
5. 最终：全量 pytest、golden 20/20、ruff check/format、package build、OpenSpec strict、
   diff check。

## 6. 反向检查

- 没有新增依赖、服务或数据库。
- M19 Skills registry、startup UI、HTTP schema 和 20 项 manifest ID 保持不变。
- 指标缺失使用 null，不把“没有证据”误报成 0 或 100。
- Evaluator 与 Generator 会话隔离，且仍受既有 sandbox/confirmation/audit 边界。

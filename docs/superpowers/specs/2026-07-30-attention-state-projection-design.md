---
comet_change: attention-state-projection
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-30-attention-state-projection
status: final
---

# Attention State Projection 技术设计

## 1. 目标和边界

本 change 只补齐三处已有接缝：`Survey/Task` 的等待输入语义、Loop 的耐久停止报告、HTTP TaskService 的安全状态投影。它不重新设计 Loop、不引入通用 workflow engine，也不改变外部副作用收据、鉴权、发布或调度语义。

公开兼容原则如下：

- 旧 `needs_info` 仍是可读的 `TaskStatus.reason` 和 `Termination` 值。
- Loop 新状态固定为 `status=stopped`、`stop_reason in {needs_input, blocked}`，而不是新增 LoopStatus。
- HTTP 原有 `status`、`reason`、`detail` 字段保留；新增 `attention` 是附加字段。
- `external_action_pending` 仍是专门的收据未决原因，优先级高于普通 blocked。

## 2. 数据模型

新增 `src/forgeagent/attention.py`：

```python
AttentionState = Literal["running", "needs_input", "blocked", "ready"]
AttentionOwner = Literal["user", "system", "external", "provider"]

class Attention(BaseModel):
    state: AttentionState
    reason: str
    owner: AttentionOwner
    required_action: str
    recovery: str
```

模型使用 `frozen=True, extra="forbid"`。reason 和其他文本有统一长度上限；构造 helper 先去除控制字符、调用既有 `mask_secrets()`，再截断。`running`/`ready` 使用稳定默认值；`needs_input`/`blocked` 必须提供非空 reason、required_action、recovery。

`TaskStatus` 增加 `attention: Attention | None = None`。`Task._derive_status()` 根据显式 round attention 或兼容 reason 生成它。`TaskOutcome` 不重复保存字段，避免两个来源漂移。

`LoopCheckpoint` 与 `LoopReport` 增加同名可选 `attention` 字段，旧 checkpoint 缺失时为 `None`。任何 report/checkpoint validator 都验证 attention 与 stop reason 的组合：`needs_input`/`blocked` 只能出现在 stopped；completed/cancelled/failed 和预算停止使用 ready，收据未决使用 blocked + `external_action_pending`。

## 3. Step/Task 数据流

1. `protocol.TaskStatus.status` 增加 `blocked`，并将其映射到 `Termination.BLOCKED`；原 `need_info` 继续映射到 `Termination.NEEDS_INFO`。
2. `RoundResult` 增加可选 attention。`ToolOutcome` 也增加可选 attention，使未来工具可以显式报告阻塞；现有 Survey 只继续返回 `needs_info=True`。
3. `Step._apply_declared_status()` 对 `blocked` 生成 attention；`Step._handle_reply()` 对 tool attention 设定 round attention 并停止当前 Step。
4. `Task._derive_status()` 保留原 reason/detail，并调用 `attention_for_reason()`：`needs_info -> needs_input/user_input_required`，`blocked -> blocked/external_dependency`，`completed/answered_in_prose/cancelled/其他终态 -> ready`。
5. `Task.run()` 在既有 `task.outcome` 事件旁发出一个 `task.attention` 事件（仅当 attention 存在），参数仅包含模型化后的安全字段。

该路径不让模型提供任意状态字段覆盖确认门、sandbox 或收据；模型只能产生 attention 请求，实际恢复仍由调用方显式执行。

## 4. Loop 集成

在 `loop.py` 中：

- `LoopStopReason` 加入 `needs_input` 和 `blocked`；两者进入 stopped 允许集合。
- `_stop(reason, attention=None)` 统一保存 status、reason、elapsed 和 attention，并在 `loop.stop` 审计中只写稳定字段。
- `_record_outcome()` 从 `TaskOutcome.status.attention` 读取 needs_input/blocked，写入 checkpoint 作为崩溃恢复证据；普通迭代清除过时 attention。
- `_run_iteration()` 在记录 outcome 后先检查 receipt store；若有未决收据，仍只停止为 `external_action_pending`。没有未决收据时，attention 为 needs_input/blocked 才停止 Loop。
- 完成、取消、预算停止和普通失败使用 `attention_for_reason()` 生成 ready（或收据未决的 blocked）。
- resume 读取旧 checkpoint 时缺失 attention 使用 reason 推导；已终结 checkpoint 仍只返回 report，不创建 Task。

## 5. HTTP 投影

`TaskRecord.public_view()` 通过一个纯函数 `_attention_for_record()` 选择唯一来源：

1. 尚未结束：`queued`/`running` -> `running`。
2. Loop report：优先 report.attention，再由 stop_reason 推导；`external_action_pending` 映射 blocked，但 reason 保留原值。
3. Collaboration report：对 `needs_confirmation` 映射 needs_input；其他终态映射 ready，运行中的 phase 仍为 running。
4. 普通 TaskOutcome：使用 `TaskStatus.attention`，旧 `needs_info` 自动映射。

公开响应中的 attention 使用 `model_dump(mode="json")`，不带 prompt、tool 参数、文件内容、checkpoint 正文或绝对路径。HTTP 仍按原 `_public_status_reason()` 规则返回 status/reason；仅将允许的新 reason 加入白名单。HTTP server 路由不需要新增 endpoint。

## 6. 审计和失败语义

`task.attention` 与 `loop.stop` 使用已有 `AuditEvent` 和 correlation 字段；参数只允许 `state/reason/owner` 及有界 action/recovery。审计写入失败不改变任务安全状态，只通过已有 sink degraded 标记暴露。不会因为 attention 事件失败而重试外部动作。

## 7. 测试矩阵

- `tests/test_attention.py`：模型枚举、默认值、掩码、截断、控制字符/额外字段拒绝、旧 reason 映射。
- `tests/test_step.py`/`tests/test_task.py`：Survey `needs_info`、声明 blocked、tool attention、ready 投影和旧断言兼容。
- `tests/test_loop_checkpoint.py`/`tests/test_loop_runner.py`：新 stop reason validator、旧 checkpoint 迁移、attention stop、receipt 优先级、resume 无重放、审计字段。
- `tests/test_http_task_service.py`/`tests/test_http_server.py`：四种 attention state、Duo/Triad confirmation、旧字段、敏感文本投影和 audit degraded。
- 文档测试更新 Loop/HTTP/threat-model 的状态表。

验收命令：专项 pytest；`uv run pytest -q`；`uv run ruff check .`；`uv run ruff format --check .`；`uv build`；`openspec validate --all --strict --no-interactive`。不运行发布上传、tag、push 或 publish change 任务。

## 8. 失败关闭和回滚

任何无法安全构造 Attention 的输入都降级为现有失败/needs_info 结构，而不是暴露未验证文本。新增字段均有默认值，旧 checkpoint 和旧 HTTP 客户端可继续工作。若验证失败，保留 change 在 build/verify 阶段，不修改 `openspec/changes/publish-v0-1-0`。

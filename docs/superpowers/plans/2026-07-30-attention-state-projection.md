---
change: attention-state-projection
design-doc: docs/superpowers/specs/2026-07-30-attention-state-projection-design.md
base-ref: 6a304bc6273a3acfd06aae81dd265ce3eeef6347
archived-with: 2026-07-30-attention-state-projection
---

# Attention State Projection 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Task、Loop 和 HTTP 增加有界、兼容的 `running / needs_input / blocked / ready` 注意力投影。

**Architecture:** 新建 `attention.py` 作为唯一状态模型与安全映射源；Step/Task 负责产生 attention，Loop 负责持久化停止状态，HTTP 只做附加式投影。旧 `needs_info`、原 HTTP 字段和 `external_action_pending` 保持兼容。

**Tech Stack:** Python 3.11、Pydantic v2、pytest、Ruff；不新增依赖。

## Global Constraints

- 不修改或推进 `openspec/changes/publish-v0-1-0`，不上传 PyPI、不创建正式 tag、不 push。
- 所有公开文本必须有界、secret-masked，不暴露 prompt、工具参数、文件内容或绝对路径。
- 先写失败测试再写最小实现；每个任务完成后运行对应专项测试。
- 不增加 scheduler、等待队列、通知、自动恢复、通用状态机或新配置面。

archived-with: 2026-07-30-attention-state-projection
---

### Task 1: Attention 核心契约

**Files:**
- Create: `src/forgeagent/attention.py`
- Create: `tests/test_attention.py`
- Modify: `src/forgeagent/task.py`

**Interfaces:**
- Produces: `Attention`, `attention_for_reason(reason, detail=None) -> Attention`
- Consumes: `mask_secrets()`、`sensitive_env_values()`

- [x] **Step 1: 写失败测试**

覆盖 running/ready/needs_info/blocked/external_action_pending 映射，非法 extra 字段拒绝，detail 的 secret masking、控制字符清理和长度限制。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/test_attention.py -q`
Expected: FAIL，原因是 `forgeagent.attention` 不存在。

- [x] **Step 3: 写最小实现**

实现 frozen/forbid 的 `Attention` Pydantic 模型和单一映射 helper；在 `TaskStatus` 增加 `attention: Attention | None = None`，不改变 `completed/reason/detail`。

- [x] **Step 4: 验证 GREEN**

Run: `uv run pytest tests/test_attention.py tests/test_task.py -q`
Expected: PASS。

### Task 2: Step/Task 兼容映射与审计

**Files:**
- Modify: `src/forgeagent/protocol.py`
- Modify: `src/forgeagent/step.py`
- Modify: `src/forgeagent/task.py`
- Modify: `src/forgeagent/tools.py`
- Modify: `tests/test_step.py`
- Modify: `tests/test_task.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Consumes: Task 1 的 `Attention` 与 `attention_for_reason()`
- Produces: `Termination.BLOCKED`、`RoundResult.attention`、`ToolOutcome.attention`

- [x] **Step 1: 写失败测试**

覆盖 Survey 旧 `needs_info` 自动得到 needs_input、模型声明 blocked、tool attention 优先停止、普通完成/取消/失败得到 ready，以及 `task.attention` 安全审计事件。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/test_step.py tests/test_task.py tests/test_audit.py -q`
Expected: 新断言 FAIL。

- [x] **Step 3: 写最小实现**

为协议增加 `blocked` 声明；Step 只传播显式 attention；Task 派生兼容 attention 并发出 bounded audit event。保留 `needs_info` reason 和旧 ToolOutcome 字段。

- [x] **Step 4: 验证 GREEN**

Run: `uv run pytest tests/test_step.py tests/test_task.py tests/test_audit.py -q`
Expected: PASS。

### Task 3: Loop 持久化与停止语义

**Files:**
- Modify: `src/forgeagent/loop.py`
- Modify: `tests/test_loop_checkpoint.py`
- Modify: `tests/test_loop_runner.py`

**Interfaces:**
- Consumes: Task 1 的 `Attention`、Task 2 的 `TaskStatus.attention`
- Produces: `LoopStopReason` 的 `needs_input`/`blocked`，checkpoint/report `attention`

- [x] **Step 1: 写失败测试**

覆盖新 stop reason/status 不变量、旧 checkpoint 缺字段兼容、Task needs_input/blocked 后停止、未决 receipt 优先、resume 不创建新 Task、审计只含安全 attention 字段。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/test_loop_checkpoint.py tests/test_loop_runner.py -q`
Expected: 新字段和 stop reason 断言 FAIL。

- [x] **Step 3: 写最小实现**

扩展 checkpoint/report；`_record_outcome()` 持久化 attention，`_run_iteration()` 在 receipt 检查后停止 needs_input/blocked；`_stop()` 统一设置 attention，旧 checkpoint 默认推导。

- [x] **Step 4: 验证 GREEN**

Run: `uv run pytest tests/test_loop_checkpoint.py tests/test_loop_runner.py -q`
Expected: PASS。

### Task 4: HTTP 附加式投影

**Files:**
- Modify: `src/forgeagent/http_task_service.py`
- Modify: `tests/test_http_task_service.py`
- Modify: `tests/test_http_server.py`

**Interfaces:**
- Consumes: Task/Loop/Collaboration 的公开 status/reason/attention
- Produces: 每个 task snapshot 的 `attention` JSON 对象

- [x] **Step 1: 写失败测试**

覆盖 queued/running、普通 needs_info、显式 blocked、Loop external_action_pending、completed/cancelled/failed ready、Triad needs_confirmation 和 HTTP JSON 兼容字段。

- [x] **Step 2: 验证 RED**

Run: `uv run pytest tests/test_http_task_service.py tests/test_http_server.py -q`
Expected: `attention` 断言 FAIL。

- [x] **Step 3: 写最小实现**

增加纯函数 `_attention_for_record()`，在 `public_view()` 附加 model dump；不新增 endpoint，不改变 `_public_status_reason()` 的旧返回值。

- [x] **Step 4: 验证 GREEN**

Run: `uv run pytest tests/test_http_task_service.py tests/test_http_server.py -q`
Expected: PASS。

### Task 5: 文档、收尾与全量验证

**Files:**
- Modify: `docs/http-task-service.md`
- Modify: `docs/threat-model.md`
- Modify: `docs/m21-loop-engineering.md`（若现有文档路径不同则更新实际 Loop 主文档）
- Modify: `openspec/changes/attention-state-projection/tasks.md`
- Create: `docs/superpowers/reports/2026-07-30-attention-state-projection-verify.md`

**Interfaces:**
- Produces: 与实现一致的状态表、威胁边界和验证证据

- [x] **Step 1: 更新文档和任务勾选**

记录状态/终态分离、恢复责任、外部收据优先级、公开字段和发布暂停。

- [x] **Step 2: 运行专项与全量验证**

Run: `uv run pytest tests/test_attention.py tests/test_step.py tests/test_task.py tests/test_loop_checkpoint.py tests/test_loop_runner.py tests/test_http_task_service.py tests/test_http_server.py -q`

Run: `uv run pytest -q`

Run: `uv run ruff check .`

Run: `uv run ruff format --check .`

Run: `uv build`

Run: `openspec validate --all --strict --no-interactive`

Expected: 全部 PASS；发布任务仍未执行。

- [x] **Step 3: 两轮最终自评**

第一轮逐项对照 proposal/spec/design/tasks；第二轮检查模糊、错误、过度保守、前后不一致、遗漏、兼容性和 secret 泄露。发现问题立即修复并重跑受影响验证。


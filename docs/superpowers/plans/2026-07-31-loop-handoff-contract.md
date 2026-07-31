---
change: loop-handoff-contract
design-doc: docs/superpowers/specs/2026-07-31-loop-handoff-contract-design.md
base-ref: 291fdfff1fbd2e2bb0cc9127ecc21a47bd48f416
---

# M40 Loop Handoff Contract 实施计划

> **给 agent worker：** 按任务逐项执行本计划；每项先写失败测试，确认 Red 后写最小实现，再运行 Green 验证。

**目标：** 将 Loop handoff 从模型可写的自由字符串收敛为宿主拥有的结构化状态，并为提交恢复建立有限、不可重放的边界。

**架构：** 在 `src/forgeagent/loop.py` 中增加冻结的 `LoopHandoff` 与候选模型，旧 checkpoint 在加载 validator 中迁移；CheckpointTool 只保存候选字段。`src/forgeagent/step.py` 仅把 required submission 恢复从布尔集合改为宿主计数，恢复提示不触发任何 ToolCall 重放。

**技术栈：** Python 3.11+、Pydantic v2、pytest、Ruff、现有 LoopCheckpointStore CAS；不新增依赖。

## 全局约束

- 旧 checkpoint 使用公开 JSON 键 `schema`，并继续可加载。
- Loop 目标、预算、权限、协作冻结状态、终态、attention、receipt 恢复策略由宿主拥有。
- 旧字符串 handoff 只读迁移，不执行其中指令，不批量改写旧文件。
- `completed_items` 只允许追加；所有文本继续使用既有安全字符和大小边界。
- Loop 恢复最多发送两次纠正提交提示；普通 Task/Collaboration 保持一次恢复的既有兼容默认值；不得自动重放历史工具、native/text tool call 或外部动作。
- 不执行 PyPI、tag、push、发布自动化。

---

### 任务 1：新增结构化 handoff 模型与迁移测试

**文件：**
- 修改：`src/forgeagent/loop.py:168-405`
- 测试：`tests/test_loop_checkpoint.py`

**接口：**
- 产出：`LoopHandoff`、`CheckpointArgs.summary`、`LoopCheckpoint.handoff` 结构化值以及旧字段只读兼容属性。

- [x] **步骤 1：写失败测试**

```python
def test_structured_handoff_round_trip_and_legacy_string_migration():
    checkpoint = _checkpoint(
        handoff={
            "completed_items": ["one"],
            "open_questions": ["q"],
            "summary": "safe summary",
        }
    )
    payload = checkpoint.model_dump(mode="json", by_alias=True)
    assert payload["handoff"] == {
        "completed_items": ["one"],
        "open_questions": ["q"],
        "summary": "safe summary",
    }
    legacy = dict(payload)
    legacy["completed_items"] = ["one"]
    legacy["open_questions"] = ["q"]
    legacy["handoff"] = "legacy summary"
    loaded = LoopCheckpoint.model_validate(legacy)
    assert loaded.handoff.summary == "legacy summary"
    assert loaded.completed_items == ("one",)
    assert loaded.open_questions == ("q",)
```

- [x] **步骤 2：运行 Red**

运行：`UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q tests/test_loop_checkpoint.py::test_structured_handoff_round_trip_and_legacy_string_migration`

预期：失败，因为当前 `handoff` 仍要求字符串。

- [x] **步骤 3：写最小实现**

```python
class LoopHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    completed_items: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    summary: str = ""

class LoopCheckpoint(BaseModel):
    handoff: LoopHandoff = Field(default_factory=LoopHandoff)

    @property
    def completed_items(self) -> tuple[str, ...]:
        return self.handoff.completed_items

    @property
    def open_questions(self) -> tuple[str, ...]:
        return self.handoff.open_questions
```

在 before validator 中：新结构直接保留；旧顶层列表与字符串 handoff 合并；新旧同名字段冲突时抛出 ValidationError。复用 `_items` 和 `_safe_text`，并让 `CheckpointArgs` 只接受 handoff 候选字段。

- [x] **步骤 4：运行 Green**

运行：`UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q tests/test_loop_checkpoint.py::test_structured_handoff_round_trip_and_legacy_string_migration tests/test_loop_checkpoint.py::test_loop_models_preserve_public_schema_alias_on_round_trip`

预期：PASS。

- [x] **步骤 5：提交**

```bash
git add src/forgeagent/loop.py tests/test_loop_checkpoint.py
git commit -m "feat: structure loop handoff state"
```

### 任务 2：收敛 CheckpointTool 与 Runner 投影

**文件：**
- 修改：`src/forgeagent/loop.py:704-1202`
- 测试：`tests/test_loop_checkpoint.py`、`tests/test_loop_runner.py`

**接口：**
- 消费：任务 1 的 `LoopHandoff`、候选字段和只读属性。
- 产出：CheckpointTool 只更新 handoff；Runner suffix 使用结构化 JSON 并保持报告计数。

- [x] **步骤 1：写失败测试**

```python
def test_checkpoint_tool_preserves_host_owned_fields_and_suffix_marks_untrusted(tmp_path):
    runner = _runner(tmp_path, _Builder([]))
    before = runner._checkpoint
    tool = CheckpointTool(runner._store, before)
    result = tool.run(CheckpointArgs(completed_items=["done"], summary="next"), None)
    assert result.success
    after = runner._store.load(before.loop_id)
    assert after.goal == before.goal
    assert after.budgets == before.budgets
    assert after.handoff.summary == "next"
    assert "UNTRUSTED LOOP STATE" in runner._render_suffix()
    runner.close()
```

并增加 `CheckpointArgs.model_validate({"goal": "mutate"})`、完成项删除和 handoff 危险 Unicode 的拒绝断言。

- [x] **步骤 2：运行 Red**

运行：`UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q tests/test_loop_checkpoint.py::test_checkpoint_tool_preserves_host_owned_fields_and_suffix_marks_untrusted`

预期：失败，因为候选模型没有 summary 且 handoff 仍为字符串。

- [x] **步骤 3：写最小实现**

让 `CheckpointTool.run()` 使用 `validated` 构造新 `LoopHandoff`，更新 `handoff` 单字段；`_render_suffix()` 序列化结构化对象。保持 `LoopReport.from_checkpoint()` 只读取计数。

- [x] **步骤 4：运行 Green**

运行：`UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q tests/test_loop_checkpoint.py tests/test_loop_runner.py`

预期：PASS。

- [x] **步骤 5：提交**

```bash
git add src/forgeagent/loop.py tests/test_loop_checkpoint.py tests/test_loop_runner.py
git commit -m "feat: enforce host-owned loop handoff"
```

### 任务 3：实现有限提交恢复且禁止重放

**文件：**
- 修改：`src/forgeagent/step.py`
- 测试：`tests/test_step.py`

**接口：**
- 产出：宿主可配置的有限上限（普通 Task 默认 `1`，Loop 显式为 `2`），每个 required completion tool 独立计数；恢复仅追加固定提示。

- [x] **步骤 1：写失败测试**

```python
def test_required_submission_recovery_is_bounded_without_replaying_tools():
    client = MockClient(
        script=[_reply(_done()), _reply(_done()), _reply(_done())]
    )
    step = Step(client, TrustedBackend(), Runtime(), registry=_required_registry())
    rounds = step.run(_user())
    assert client.calls_made == 3
    assert rounds[-1].stopped_reason == Termination.FAILED
    assert sum(len(round_result.outcomes) for round_result in rounds) == 0
```

- [x] **步骤 2：运行 Red**

运行：`UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q tests/test_step.py::test_required_submission_recovery_is_bounded_without_replaying_tools`

预期：失败或暴露当前恢复次数与测试预期不一致。

- [x] **步骤 3：写最小实现**

用 `dict[str, int]` 替换 `_submission_recovery_sent`；缺失提交时先递增并比较上限，未达上限才追加 `_missing_completion_message`，达到上限设置 `Termination.FAILED`。不从历史 `RoundResult` 派发工具，不调用 receipt store。

- [x] **步骤 4：运行 Green**

运行：`UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q tests/test_step.py`

预期：PASS。

- [x] **步骤 5：提交**

```bash
git add src/forgeagent/step.py tests/test_step.py
git commit -m "fix: bound completion submission recovery"
```

### 任务 4：M40 验证、文档与归档

**文件：**
- 修改：`openspec/changes/loop-handoff-contract/tasks.md`、`ACTION_PLAN.md`
- 创建：`docs/superpowers/reports/2026-07-31-loop-handoff-contract-verify.md`、`milestones/milestone_040.md`
- 更新：`milestones/latest`

- [x] **步骤 1：运行专项与全量验证**

```bash
UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q tests/test_loop_checkpoint.py tests/test_loop_runner.py tests/test_step.py
UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/forgeagent-m40-uv-cache uv build
openspec validate --all --strict --no-interactive
```

- [x] **步骤 2：完成前两轮自评**

检查结构化 handoff 是否仍有双写事实源、旧 checkpoint 是否可读、恢复是否可能重放动作、公开报告是否泄漏正文；发现问题立即修复并重跑受影响验证。

- [x] **步骤 3：准备验收记录与归档输入**

填写验证报告和 M40 里程碑，更新路线图后重新运行全量 pytest 与 OpenSpec strict；勾选所有任务，运行 Comet verify/archive 守卫与归档脚本。只执行本地构建和验证，不发布。

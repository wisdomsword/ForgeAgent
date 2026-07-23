---
change: memory-runtime
design-doc: docs/superpowers/specs/2026-07-23-memory-runtime-design.md
base-ref: 840f649821b1c5440ee22b43b7ee213c4d44f8b6
archived-with: 2026-07-23-memory-runtime
---

# M18 Memory Runtime 实施计划

> **面向 agent worker：** 任务按 checkbox 执行；每个任务遵循 TDD Red-Green-Refactor。

**目标：** 在 M15 identity 与 M17 bounded context 之间加入显式、确定性、可审计的 session/project memory 生命周期。

**架构：** `protocol.py` 只负责解析 `MemoryCandidate`，新增 `memory.py` 负责候选准入、两级存储、Markdown 编解码和原子替换；Task/CLI/HTTP 只负责装配 manager snapshot。现有 identity、context、audit 和 HTTP schema 契约保持不变。

**技术栈：** Python 3.11、Pydantic v2、stdlib `tempfile/os.replace/re`, 现有 pytest/ruff；不增加依赖。

## 全局约束

- 只接受 fact/preference/decision；procedure 必须分流到 Skill。
- `--no-memory` 阻止 session/project 的加载、注入和写入；HTTP 不共享 session。
- project MEMORY.md 只能通过同目录临时文件加 `os.replace` 更新，失败保留旧文件。
- 审计只记录 scope/kind/key/reason/task correlation，不记录 content、secret、全文或绝对路径。
- 显式 `system_prompt` 和 `--no-identity` 既有优先级不变；M17 context policy 仍是最终预算边界。
- 不实现向量检索、RAG、摘要、置信度、衰减、团队作用域或 Skill 写入。

archived-with: 2026-07-23-memory-runtime
---

### Task 1：MemoryCandidate 协议与核心存储

**文件：**
- 修改：`src/forgeagent/protocol.py`
- 新增：`src/forgeagent/memory.py`
- 测试：`tests/test_protocol.py`、`tests/test_memory.py`

**接口：**
- `parse(text, ...) -> ParseResult` 增加 `memory_candidates: list[MemoryCandidate]`。
- `MemoryManager(allowed_root: str, *, audit_sink: AuditSink | None = None, enabled: bool = True)`。
- `MemoryManager.load() -> None`、`apply(candidate: MemoryCandidate, task_id: str | None = None) -> MemoryResult`、`render() -> str`、`disable() -> None`。

- [x] **步骤 1：写失败测试**

```python
def test_parse_memory_marker_and_remove_from_body():
    result = parse('answer <!-- Memory: {"scope":"project","kind":"fact","key":"editor","content":"vim"} -->')
    assert result.memory_candidates[0].key == "editor"
    assert "Memory:" not in result.body

def test_procedure_candidate_is_rejected_without_write(tmp_path):
    manager = MemoryManager(str(tmp_path))
    outcome = manager.apply(MemoryCandidate(scope="project", kind="procedure", key="steps", content="run command first"))
    assert outcome.status == "rejected"
    assert "Skill" in outcome.reason
    assert not (tmp_path / ".forgeagent" / "MEMORY.md").exists()
```

- [x] **步骤 2：运行 RED**：`uv run pytest -q tests/test_protocol.py tests/test_memory.py -k memory`，预期因符号不存在失败。
- [x] **步骤 3：实现最小协议与 manager**：增加 Pydantic 模型、Memory 正则标记、解析错误复用 `ParseError`；manager 实现 key/content 上限、procedure/注入/secret/控制字符拒绝、受控 Markdown、session 字典和 `os.replace` 原子写入。
- [x] **步骤 4：运行 GREEN/ruff**：`uv run pytest -q tests/test_protocol.py tests/test_memory.py -k memory && uv run ruff check src/forgeagent/protocol.py src/forgeagent/memory.py tests/test_memory.py`。
- [x] **步骤 5：提交**：`git add src/forgeagent/protocol.py src/forgeagent/memory.py tests/test_protocol.py tests/test_memory.py && git commit -m "feat: add deterministic memory core"`。

### Task 2：Task/Step 与 Identity 注入、生命周期审计

**文件：**
- 修改：`src/forgeagent/task.py`、`src/forgeagent/step.py`、`src/forgeagent/identity.py`、`src/forgeagent/audit.py`
- 测试：`tests/test_task.py`、`tests/test_step.py`、`tests/test_identity.py`、`tests/test_audit.py`、`tests/test_mock_replay_e2e.py`

**接口：** Task 接收 `memory_manager: MemoryManager | None = None`；Task 结束后按 round 候选调用 `manager.apply`，system prompt 使用同一次 bounded snapshot；显式 `system_prompt` 仍短路 identity。

- [x] **步骤 1：写失败测试**：RecordingClient 断言第一 Task 的 project 候选进入第二 Task 的 system message；session 候选不落盘；audit event 不含 content。
- [x] **步骤 2：运行 RED**：`uv run pytest -q tests/test_task.py tests/test_mock_replay_e2e.py -k memory`，预期 Task 尚不接受 manager。
- [x] **步骤 3：实现装配**：Task 读取 manager.render() 合成 `ApprovedIdentity.memory`；Step 将 `ParseResult.memory_candidates` 交回 Task；audit 使用 `emit_audit` 写 `memory.*` 事件；不改变 Termination 或 HTTP projection。
- [x] **步骤 4：运行 GREEN**：`uv run pytest -q tests/test_task.py tests/test_step.py tests/test_identity.py tests/test_audit.py tests/test_mock_replay_e2e.py -k 'memory or audit'`。
- [x] **步骤 5：提交**：`git add src/forgeagent/task.py src/forgeagent/step.py src/forgeagent/identity.py src/forgeagent/audit.py tests && git commit -m "feat: integrate memory with task lifecycle"`。

### Task 3：CLI/HTTP 控制与配置

**文件：**
- 修改：`src/forgeagent/cli.py`、`src/forgeagent/http_task_service.py`、`src/forgeagent/headless.py`
- 测试：`tests/test_cli.py`、`tests/test_http_task_service.py`、`tests/test_headless.py`

- [x] **步骤 1：写失败测试**：REPL 驱动 `/remember`、`/memory`、`/reload`；`--no-memory` 下 prompt 不含项目记忆；HTTP 连续任务证明没有 session 泄漏。
- [x] **步骤 2：运行 RED**：`uv run pytest -q tests/test_cli.py tests/test_http_task_service.py -k memory`。
- [x] **步骤 3：实现入口装配**：增加 `/memory`/`/remember` usage 与 handler；REPL 持有 manager 并在 reload 时事务化刷新；parser 增加 `--no-memory`；HTTP 每任务创建 project-only manager，不增加请求/响应字段。
- [x] **步骤 4：运行 GREEN/ruff**：`uv run pytest -q tests/test_cli.py tests/test_http_task_service.py tests/test_headless.py -k memory && uv run ruff check src/forgeagent/cli.py src/forgeagent/http_task_service.py src/forgeagent/headless.py`。
- [x] **步骤 5：提交**：`git add src/forgeagent/cli.py src/forgeagent/http_task_service.py src/forgeagent/headless.py tests/test_cli.py tests/test_http_task_service.py tests/test_headless.py && git commit -m "feat: add memory controls to cli and http"`。

### Task 4：文档、golden 与回归

**文件：**
- 修改：`docs/text-protocol-spec.md`、`docs/threat-model.md`、`README.md`、`tests/golden/cases.py`、`tests/golden/manifest.py`
- 测试：`tests/test_golden_candidates_memory.py`（新增）

- [x] **步骤 1：补文档与候选**：说明 Memory 标记、准入拒绝、Skill 分流、投毒边界和 `--no-memory`；新增命中/未命中/拒绝候选但不提前加入 verified manifest。
- [x] **步骤 2：运行定向验证**：`uv run pytest -q tests/test_golden_candidates_memory.py tests/test_golden_runner.py`。
- [x] **步骤 3：运行全量验证**：`uv run pytest -q`、`uv run ruff check .`、`uv run python -m tests.golden.runner`、`openspec validate memory-runtime --strict`、`git diff --check`。
- [x] **步骤 4：提交**：`git add docs README.md tests/golden tests/test_golden_candidates_memory.py && git commit -m "docs: document memory runtime boundaries"`。

### Task 5：终审与 Comet 收尾

- [x] **步骤 1：按 `requesting-code-review` 做一次 whole-change 审查**：检查 scope、prompt 顺序、原子写入、secret masking、HTTP/session 隔离和 M15/M17 回归；Critical 必须修复。
- [x] **步骤 2：若审查或全量验证发现失败，按 systematic-debugging 追根因，增加最小回归测试并修复后重跑受影响命令。**
- [x] **步骤 3：勾选 `openspec/changes/memory-runtime/tasks.md` 全部完成，写验证报告和 `milestones/milestone_018.md`，更新 `milestones/latest`。
- [x] **步骤 4：运行 `node .agents/skills/comet/scripts/comet-guard.mjs memory-runtime build --apply`，随后进入 verify。

## 计划自评审

- 覆盖了新 capability 的七类需求：协议、准入、作用域、原子持久化、用户控制、审计、回归。
- 没有新增依赖、数据库或未来 M19/M20 组件；HTTP schema 明确保持不变。
- 所有跨任务接口签名在相邻任务中一致：Task 使用 `MemoryManager`，manager 返回 `MemoryResult`，parser 提供 `memory_candidates`。


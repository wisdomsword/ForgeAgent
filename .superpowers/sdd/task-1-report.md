# Task 1 实施报告：收据模型、ID 兼容与安全持久化

## 状态

DONE_WITH_CONCERNS

Task 1 的收据模型、canonical digest、状态迁移、revision CAS、目录 fd 绑定、
symlink-safe descriptor-relative 读写、原子临时文件替换、私有权限、审计投影和
bounded/masked 字段已完成。receipt 自行生成 `uuid4().hex` action ID；既有任意格式的
`ToolCall.id` 保持兼容。

## Review Fix Round 1

修复了审查发现：创建工厂不再允许覆盖 action ID、phase、resolution、revision 或时间戳；模型拒绝不一致的 phase/certainty/remote_ok/evidence 组合；创建输入的边界错误统一转换为 `ReceiptError`；补充了创建覆盖、状态组合、越界输入、目录替换、CAS 并发和畸形记录测试。

验证：`uv run pytest tests/test_external_actions.py -q` -> `18 passed, 1 warning`；`uv run ruff check src/forgeagent/external_actions.py tests/test_external_actions.py` -> `All checks passed!`；`uv run ruff format --check src/forgeagent/external_actions.py tests/test_external_actions.py` -> `2 files already formatted`。

修复提交：`50b65c2`。剩余 warning 是 Pydantic 对字段名 `schema` 的兼容提示，未改变行为。

## TDD 证据

### RED

命令：

```bash
uv run pytest tests/test_external_actions.py -q
```

结果：`1 failed, 4 passed`。失败原因是 strict-extra 测试通过未知参数调用
`ExternalActionReceipt.new_prepared()` 时工厂直接抛出 `TypeError`，尚未产生预期的
Pydantic `ValidationError`。

### GREEN

最小修复：`new_prepared()` 透传未知关键字给 strict Pydantic 模型；模型仍使用
`ConfigDict(extra="forbid")`，因此未知字段被模型拒绝。

命令：

```bash
uv run pytest tests/test_external_actions.py -q
```

结果：`5 passed, 1 warning`。唯一 warning 是 Pydantic 对字段名 `schema` 覆盖父类
属性的既有命名提示，不影响测试结果。

## 提交

提交 hash：`32d85d9a8f28fc487b83831b047c4d7f8b4c10a8`。

变更文件：

- `src/forgeagent/external_actions.py`
- `tests/test_external_actions.py`
- `.superpowers/sdd/task-1-report.md`

## 风险信号

- 安全：**YES**。收据是外部动作 fail-closed 边界，涉及 symlink、目录替换、私有权限、
  原子持久化、脱敏和禁止原始参数落盘；focused 存储测试通过，尚未做外部安全审计。
- 并发：**YES**。每收据 advisory lock + revision CAS；当前 focused 测试覆盖 stale revision，
  更广的并发压力仍属于后续验证范围。
- 跨模块：**YES**。模块依赖现有 audit/secret policy，并由后续 MCP/Loop 任务装配；本任务
  未修改这些调用方。
- API：**YES（新增）**。新增 `forgeagent.external_actions` 公共模型/存储接口；既有
  `ToolCall.id` 未收紧。
- 大 diff：**YES**。收据存储实现本身跨越模型、校验、转换和安全文件 I/O；本次未新增
  抽象、依赖或额外功能。

## 关注事项

- focused 测试通过，但完整仓库测试、Ruff 和后续 MCP/Loop 集成验证尚未在本任务执行。
- `schema` 字段会触发 Pydantic warning；这是设计字段名兼容要求导致的已知提示。

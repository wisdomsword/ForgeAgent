---
change: external-action-receipts
status: verified
release: PyPI paused
---

# 外部动作收据验证报告

## 结果

- 收据模型与安全存储：四态 delivery、独立 resolution、revision CAS、目录绑定、原子写入、脱敏与畸形记录 fail-closed。
- MCP：保留 `ok/text`，补充 `not_dispatched`、`confirmed`、`unknown`；受保护调用禁止无收据 dispatch；`unknown` 固定反馈且不自动重放。
- Loop/入口：未决收据阻断模型/Task 构造，使用 `external_action_pending`；CLI/协作入口复用同一 allowed-root store。
- CLI：增加有界 `forgeagent receipts list` 与显式 `resolve`，不启动 MCP、不触发外部动作。

## 验证命令

```text
uv run pytest -q                         -> 2433 passed, 10 skipped
uv run ruff check .                      -> All checks passed
uv run ruff format --check .             -> 121 files already formatted
uv build                                 -> source distribution and wheel built
openspec validate external-action-receipts --strict --no-interactive -> valid
```

专项聚合测试为 758 passed；收据专测为 18 passed。首次全量测试发现 Pydantic `schema` 导入 warning，已改为 alias 字段并复验；剩余测试全绿。

## 两轮自评

1. 契约/安全：复核 phase 与 resolution 分离、confirmed 语义、unknown 不重放、no-dispatch、根目录绑定、锁/CAS、字段脱敏和任意 operation ID 兼容；已修复创建覆盖与状态组合漏洞。
2. 集成/范围：复核 Loop、CLI、HTTP/协作装配、无 MCP 兼容、文档一致性与范围边界；未扩展到 FileWrite/Exec/Edit/WebFetch，未新增依赖或 HTTP reconciliation endpoint。

## 发布边界

`openspec/changes/publish-v0-1-0` 仍保持未归档，发布任务未推进；本次没有上传 PyPI、创建正式 tag、push 或执行发布自动化。

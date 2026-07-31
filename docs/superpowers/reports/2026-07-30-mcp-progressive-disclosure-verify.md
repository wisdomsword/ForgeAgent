# MCP Progressive Disclosure 验证报告

- change: `mcp-progressive-disclosure`
- 日期: 2026-07-30
- 状态: 通过；PyPI 发布、tag、push 保持暂停

## 交付范围

- system prompt 的 MCP section 改为有界目录：public server、工具名、单行短摘要、权限提示和 `MCPDescribe` 指引；不注入完整 input schema。
- 新增只读 `MCPDescribe`：从当前 available discovery 快照读取单个工具的有界 description/schema/权限信息，不连接 server、不执行外部动作、不创建 receipt。
- 保留既有 `MCP` ToolCall 的路由、确认、receipt、失败和 masking；CLI `/mcp tools` 仍读取完整 masked 工具诊断清单。
- 文档和威胁模型明确记录目录/详情边界、secret masking、控制字符清理、超长 schema 安全降级，以及 Code Mode/Worker/远程缓存不在范围。

## 验证证据

```text
uv run pytest -q
2451 passed, 10 skipped in 167.57s

uv run ruff check .
All checks passed!

uv run ruff format --check .
123 files already formatted

uv build
Successfully built dist/forgeagent-0.1.0.tar.gz
Successfully built dist/forgeagent-0.1.0-py3-none-any.whl

openspec validate --all --strict --no-interactive
Totals: 26 passed, 0 failed (26 items)
```

专项 MCP/工具/协议/Task/CLI 回归：`612 passed`；控制字符修复后专项目录/详情测试：`2 passed`。

## 两轮最终自评

### 第一轮：契约与实现对照

- [x] proposal/design/spec/tasks、实现和测试都只包含 MCP 渐进披露，不改变 server 生命周期、MCP 调用、confirmation、receipt 或发布流程。
- [x] OpenSpec delta 使用 `ADDED`/`MODIFIED` 正确格式，并已通过 strict 校验。
- [x] CLI 既有 `/mcp tools` 行为保持完整 masked 描述/诊断字段；schema 改为由 `MCPDescribe` 按需读取，已修正规格中的过度承诺。
- [x] `MCPDescribe` 只读快照，未知工具失败可恢复；registry 仅在 MCP-enabled 时注册。

### 第二轮：安全、兼容与遗漏

- [x] description 先 secret mask，再做控制字符清理和长度上限；schema 使用 `allow_nan=False`，序列化失败或超限返回 `{}`。
- [x] 目录不泄露 input schema；详情 continuation 明确下一步；重复查询不触发网络或连接操作。
- [x] 现有 MCP confirmation/receipt 测试与全量回归通过；无新增依赖、endpoint、配置、远程缓存或 Code Mode/Worker。
- [x] 未执行 PyPI 上传、tag、push，也未修改/推进 `openspec/changes/publish-v0-1-0`。

## 独立审查

本次工作区未自动提交；M29 和用户既有脏文件均保留。已尝试委派独立 reviewer，但本会话未收到可用反馈；因此以两轮主 Agent 自审、专项/全量回归、Ruff、build 和 OpenSpec strict 作为代码评审证据。

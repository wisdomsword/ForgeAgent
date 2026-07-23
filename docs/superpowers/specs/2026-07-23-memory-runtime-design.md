---
comet_change: memory-runtime
role: technical-design
canonical_spec: openspec
status: final
---

# M18 Memory Runtime 技术设计

## 1. 设计范围

M15 提供了 `.forgeagent/MEMORY.md` 的加载和身份组合，M17 提供了调用前有界上下文视图。M18 在这两者之间增加记忆生命周期：候选提取、确定性准入、session/project 作用域、冲突替换、用户控制和最小披露审计。

明确不做向量检索、RAG、语义摘要、置信度模型、时间衰减、用户/团队作用域、Skill 文件写入或额外 LLM 提取调用。OpenSpec delta spec 是行为事实源，本文只细化实现。

## 2. 数据模型与协议

`src/forgeagent/protocol.py` 增加：

```python
class MemoryCandidate(BaseModel):
    scope: Literal["session", "project"]
    kind: Literal["fact", "preference", "decision", "procedure"]
    key: str
    content: str
```

响应解析器识别 `<!-- Memory: {"scope":"project",...} -->`，校验 JSON 后把合法候选放入 `ParseResult.memory_candidates`，并从 `body` 移除标记。坏 JSON 或 schema 错误复用 `ParseError`，不会产生候选。候选标记不影响 Task 完成状态；同一响应允许多个标记，但 manager 对 key 按出现顺序处理。

CLI `/remember <scope> <key>=<content>` 只负责解析用户输入并构造上述模型，随后走完全相同的 manager API。`/memory` 只读渲染，不调用模型。

## 3. MemoryManager

新增 `src/forgeagent/memory.py`，避免引入 manager/factory 层级，只提供一个可直接测试的类和少量纯函数：

- `load()`：读取项目 `.forgeagent/MEMORY.md`，只接受受控条目格式；session 从空字典开始。
- `apply(candidate, task_id=None)`：检查 enabled、规范化 key/content、执行准入规则，然后更新目标作用域。
- `render()`：返回有界的 session/project Markdown 文本，所有外部内容在模型和 `/memory` 输出前都走现有 `mask_secrets`。
- `disable()`：阻止加载、注入和写入，发出一次 `memory.disabled` 诊断。

受控文件格式为：

```markdown
<!-- forgeagent-memory-v1 -->
- key: value
```

`key` 是 `[a-z0-9][a-z0-9._-]{0,79}`，`value` 是单行、UTF-8、最多 512 字节的事实内容。未知 Markdown、控制字符、重复 key 之外的自由格式一律跳过并输出脱敏诊断，不执行其指令性语义。session/project 各自最多 64 条，渲染总字节受 32 KiB 上限约束；超出时拒绝新候选而不截断旧事实。

project 更新在 `.forgeagent` 目录内创建临时文件，写入完整的新内容后调用 `os.replace`；任何 OSError 都返回 `persistence_error`，并保留原文件。相同 key 后写入者胜并返回 `replaced`，新 key 返回 `accepted`。

## 4. 准入规则

准入顺序固定，便于表驱动测试和审计：

1. `enabled`、scope、kind、key、content 基础校验。
2. `kind == procedure` 直接拒绝，reason 为 `procedure_requires_skill`。
3. 既有 `sensitive_env_values()` 与 `mask_secrets` 检查；候选原文只在进程内短暂存在，审计永不写入。
4. 拒绝控制字符、换行、超长内容和有限的提示注入模式（`ignore previous`、`reveal secret`、`system prompt`、`execute command` 等，不区分大小写）。
5. 通过后写入目标作用域。

这些规则是准入门，不是执行安全边界；后续 Task 仍使用既有协议、确认门和 sandbox。

## 5. Task、Identity 与入口装配

`Task` 接受一个可选的 memory text 或 manager snapshot。只要调用方显式传入 `system_prompt`，身份和记忆均不自动混入，保持现有库调用契约。否则 `ApprovedIdentity.memory` 使用 manager 的安全渲染文本，再调用现有 `compose_system_prompt`；M15 的固定协议、信任摘要和 MCP 工具段顺序不变。

CLI 在 REPL 启动时创建一个 project-root manager，加载已确认的 MEMORY，并保留 session 字典；每个 goal 前取得 snapshot，Task 结束后把每轮的 `memory_candidates` 依次交回 manager。`/reload` 事务化刷新 project 文件和 manager snapshot，但不把 session 候选转写为 project。`--no-memory` 创建 disabled manager，且 `/remember` 只返回 disabled 结果。

单次 CLI 运行使用同样的 project-only manager，任务结束即释放。HTTP/headless 每个任务创建 project-only manager，永不共享进程级 session；请求/响应 JSON schema、鉴权、取消和安全投影不变。

## 6. 审计

manager 通过既有 `AuditSink` 记录：`memory.accepted`、`memory.rejected`、`memory.replaced`、`memory.persistence_error`、`memory.disabled`。参数仅包含 `scope`、`kind`、掩码后的 `key`、有限 `reason` 和 task correlation；不含 content、MEMORY 全文、secret、token 或绝对路径。audit sink 失败复用现有 `audit_degraded` fail-open 行为。

## 7. 错误与兼容性

- 解析错误进入已有 feedback，不改变完成状态。
- project 写入失败不回滚已经完成的 Task，也不覆盖旧文件。
- 畸形旧 MEMORY 文件按无合法条目加载；不需要迁移脚本。
- M17 context policy 在 system prompt 生成后继续执行预算，memory manager 不复制或修改 conversation。
- 未启用 manager 的直接 `Task` 调用行为保持不变，不读取 home 或项目文件。

## 8. 测试矩阵

- `tests/test_memory.py`：schema、标记解析、准入表、投毒/secret、Markdown codec、原子失败、冲突替换、渲染上限。
- `tests/test_protocol.py`：Memory 标记与现有 code/tool/status 标记组合，正文剥离和坏标记错误。
- `tests/test_task.py`/`tests/test_mock_replay_e2e.py`：跨 Task session/project 记忆、project 重启、完成语义不变、memory 不进入 HTTP schema。
- `tests/test_cli.py`：`/memory`、`/remember`、`/reload`、`--no-memory` 和 session 隔离。
- `tests/test_audit.py`/`tests/test_http_task_service.py`：事件字段、掩码、audit degrade、HTTP project-only。
- golden 候选覆盖命中、未命中、程序性拒绝和注入拒绝，不在 runner 断言完成前宣称已验证。

## 9. 评审结论

两轮自评审均确认：候选必须显式、准入必须确定性、project 写入必须原子、两级作用域必须由入口持有、`--no-memory` 必须阻止读取和写入、HTTP 不得泄漏 session；没有发现与 M15/M17 或 M18 OpenSpec 场景的矛盾。

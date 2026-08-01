# 里程碑 M47: 客户端生命周期与输入契约加固

- 状态: 已完成并归档
- 起止: 2026-08-01 ~ 2026-08-02
- 对应 ACTION_PLAN 行: M47（本里程碑新增）
- 前置里程碑: [milestone_046](milestone_046.md)
- OpenSpec change: `harden-client-lifecycle-and-input-contracts`

## 目标与范围

修复 provider SDK client 重复创建和关闭责任不清；在 CLI、smoke、evaluate、HTTP 和异常路径补齐本调用资源所有权；为模型生成参数、能力与 registry entry 增加有限正数约束；将 M34 生命周期 verifier 改为跨 Python 3.11+ 稳定的规范化源码片段摘要。保持输出、HTTP 返回、工具/流式行为和依赖边界不变；不执行 PyPI、tag、push 或发布自动化。

## 方案设计

- `ModelClient.close()` 提供具体 no-op 默认契约，注入 transport 仍由调用方拥有。
- OpenAI-compatible 与 Anthropic client 懒创建并共享 SDK client，provider `close()` 幂等且不让 close 错误覆盖任务结果。
- 入口层按 Task 后 client 的既有顺序关闭本调用创建的资源；共享 REPL/服务资源保留会话级所有权。
- 使用 Pydantic 正数/有限浮点约束，并以显式 `None` 选择 capability 上限。
- verifier 继续用 AST 定位目标，但对规范化源片段做 UTF-8 摘要，跨解释器稳定且保留源码变更检测。

## 子任务清单

- [x] provider 生命周期契约、共享 SDK transport、幂等 close 与专项测试。
- [x] CLI、smoke、evaluate、HTTP 和异常所有权路径及回归测试。
- [x] 模型输入有限正数约束、显式 fallback 与非法值测试。
- [x] M34 verifier 跨 Python 3.11/3.12/3.14 稳定摘要与变更检测。
- [x] 全量验证、两轮评审、M41 行预算修复和收尾证据。

## 交付物清单

- [x] `src/forgeagent/client.py`、`openai_compatible_client.py`、`anthropic_client.py` — 生命周期契约与 provider 资源管理。
- [x] `src/forgeagent/cli.py`、`_cli_parser.py`、`_cli_http.py` — 所有权边界清理。
- [x] `src/forgeagent/models.py`、`model_registry.py` — 输入契约约束。
- [x] `tests/test_cli.py`、`test_http_server.py`、provider/model/lifecycle 测试 — 回归与跨版本证据。
- [x] [验证报告](../docs/superpowers/reports/2026-08-01-harden-client-lifecycle-and-input-contracts-verify.md) — 命令、输出、评审与风险。

## 三次评审

### 技术方案评审

- [x] 生命周期、输入契约和 verifier 设计与批准的 M47 范围一致。
- [x] 未引入新依赖、Rust 重写或发布目标；流式、HTTP 和公开错误投影保持原契约。

### 代码评审

- [x] 各子任务完成实现后均有 focused review；closeout 做两轮独立读码复核。
- [x] 修复 M41 行预算超限（`cli.py` 1820 → 1798 行），不改变行为。
- [x] 修复跨版本 verifier 子进程隐式依赖 pytest 的环境缺陷。
- [x] 无 Critical/Important 遗留项。

### 验收评审

- [x] 全量 `2781 passed, 11 skipped`；Ruff check、format、`uv build` 通过。
- [x] 模型/CLI/HTTP/协作/lifecycle 专项在 Python 3.11、3.12、3.14 均 `511 passed, 1 skipped`。
- [x] OpenSpec strict `37/37`，跨版本 digest probe 通过。
- [x] 无新增 skip；已有环境依赖 skip 已记录。

## 遗留问题

- [ ] 全量测试中的 11 个环境依赖 skip — 影响：容器/外部运行时在当前主机不可用 — 计划：在具备对应运行时的 CI/主机复验，不阻塞 M47。
- [ ] M43 仍为 `keep_python` — 影响：未达到 Rewrite 迁移阈值 — 计划：保持 Python，待六项指标共同越阈值后另立 change。

## 续接指引

M47 完成后继续以 `milestones/latest` 和 `ACTION_PLAN.md` 为准。客户端生命周期和模型输入契约已有稳定边界；后续只有真实 Memory 迁移需求、Rewrite 六项指标越阈值或 HTTP 从 loopback-only 进入外部控制面时，才启动对应独立里程碑。不要恢复 PyPI、tag、发布自动化或无证据的 Rust 重写。

# M17 Runtime Context Engineering 验证报告

- 日期：2026-07-23
- 分支：`codex/m17-runtime-context-engineering`
- Change：`runtime-context-engineering`

## 结论

M17 通过完整验证。实现为 CLI、REPL 与 HTTP 提供同一条服务端控制的 context
policy 路径，并交付有界且诚实的工具反馈、provider 归一化 prompt 分母、CLI/session
cache hit rate，以及对应的审计与文档契约。

最终全分支复审为 `PASS / APPROVED`，问题数为
`0 Critical / 0 Important / 0 Minor`。当前分支保持原状，未合并、未 push。

## OpenSpec 验证

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| 完整性 | PASS | 18/18 tasks 完成；7/7 requirements 已实现 |
| 正确性 | PASS | 31/31 scenarios 有实现与自动化测试证据 |
| 一致性 | PASS | proposal、OpenSpec design、Superpowers 技术设计与实现无矛盾 |

未发现 CRITICAL、WARNING 或 SUGGESTION。关联技术设计文件
`docs/superpowers/specs/2026-07-22-runtime-context-engineering-design.md` 存在且与本 change
一致；delta spec 与技术设计没有漂移。

## 验证矩阵

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 全量测试 | `uv run pytest -q` | `1351 passed, 11 skipped` |
| 静态检查 | `uv run ruff check .` | 通过 |
| 离线 golden | `.venv/bin/python -m tests.golden.runner --output-dir /tmp/forgeagent-m17-golden-final` | `20/20 passed` |
| OpenSpec | `openspec validate runtime-context-engineering --strict` | valid |
| 空白检查 | `git diff --check` | 通过，无输出 |

第一次在受管沙箱内运行全量测试时出现 11 个 M16 loopback 失败、1 个构建失败，
以及 5 个仍使用 `Step.run([])` 的陈旧 policy wiring fixture 失败。fixture 已改为提供
必需的 system + initial-goal 前缀。随后在受管沙箱外重新运行同一全量测试，使
loopback 分配与 `uv build` 可以实际执行，得到上表最终结果。

全分支评审随后发现两个配置契约问题：falsey YAML 根可能被误当作配置缺失；混合
feedback limit override 未遵循已批准的独立自适应公式。两项均以回归测试修复。
最终窄范围复审确认 2/2 问题关闭，之后再次运行了上表完整验证矩阵。

## 聚焦证据

- Provider 分母：Anthropic 与 OpenAI-compatible 的 streaming/non-streaming、usage
  缺失和合法零值路径均有覆盖。
- Context policy 与 feedback：不可淘汰前缀、最新 round fail-fast、完整交互单元滑动、
  保留消息不变性、水位分配、head/tail 截断、诚实 continuation 和 metadata overflow
  均有覆盖。
- CLI 与审计：ratio-of-sums、永久未知分母、异常 usage、REPL session 累计、registry/
  context 事务化 reload、注入 factory，以及数值/null 审计比率均有覆盖。
- HTTP/M16 回归：bearer 鉴权、严格请求 schema、取消、有界安全投影、审计降级与关联、
  精确 allowlist 和 MCP autoApprove 隔离通过组合回归测试。
- 长对话 replay：小窗口确定性任务按完整 round 滑动，保持稳定前缀和保留消息值，暴露
  截断协议，保留原始 `ToolOutcome`，并最终完成。

## 遗留边界

- Token 估算刻意采用本地近似；provider tokenizer 仍可能通过既有结构化 client error
  拒绝极端边界请求。
- 未调用真实 provider API；adapter 测试使用具有代表性的 SDK 响应形状。
- M17 只提供 sliding-window 保留，不提供语义摘要；摘要能力不在本里程碑范围内。

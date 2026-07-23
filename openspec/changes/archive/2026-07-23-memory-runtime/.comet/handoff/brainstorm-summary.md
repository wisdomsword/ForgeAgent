# Brainstorm Summary

- Change: memory-runtime
- Date: 2026-07-23

## 确认的技术方案

采用显式 `MemoryCandidate` 标记与 `/remember` 的统一候选入口；新增一个轻量 `MemoryManager` 负责确定性准入、session/project 存储、Markdown 编解码、原子替换、渲染和审计。模型候选不直接写文件，所有候选先经过同一规则表：只接受 fact/preference/decision，procedure 分流到 Skill，注入/secret/控制字符/长度违规拒绝。CLI 持有 REPL 级 manager；HTTP 每任务只加载 project 作用域。记忆以安全渲染结果作为 M15 identity 的 memory 段，M17 context policy 继续负责最终预算。

## 关键取舍与风险

- 不增加第二次 LLM 提取调用、向量库、RAG、置信度或摘要，保证确定性和最小 diff。
- project 冲突采用后写入者胜，但通过 `/memory`、可编辑 MEMORY.md 和 `--no-memory` 保持可见、可纠正、可停用。
- 规则式投毒检测不是安全边界；sandbox、协议和工具确认仍承担执行安全。
- project 写入采用同目录临时文件 + `os.replace`，失败保留旧文件。

## 测试策略

表驱动准入/协议单测；跨 Task mock replay；project 重启与冲突替换；CLI `/memory`、`/remember`、`/reload`、`--no-memory`；HTTP 无 session 泄漏；审计最小披露；golden 命中/拒绝/投毒回归；全量 pytest、ruff、OpenSpec strict 和 diff check。

## Spec Patch

无。

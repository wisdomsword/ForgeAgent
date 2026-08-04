## Context

M47 的 `Step._run_rounds()` 在响应没有工具结果、解析错误或显式终态时，把非空正文先视为需要协议纠偏：第一次追加 `_PROSE_NUDGE`，第二次才以 `answered_in_prose` 软完成。旧分支 change `2026-08-03-accept-direct-prose-answers` 已验证直接软完成和流式正文去重；本 change 只把该行为移植到 M47。

## Goals / Non-Goals

**Goals:**

- 普通非空纯文本回答在首轮直接以 `answered_in_prose` 结束，并保持“未执行验证”语义。
- 流式与非流式终端都只持久显示一份纯文本正文。
- required completion tool、工具反馈、解析错误和显式终态的 M47 边界保持不变。

**Non-Goals:**

- 不通过关键词重新分类用户意图。
- 不把 prose 软完成报告为执行验证完成。
- 不移植旧分支的无关提交，不新增配置、状态或抽象。

## Decisions

1. 以 M47 为目标树，先移植旧 change 的边界测试，再重建最小实现；冲突时保留 M47 的协作与完整性增强。
2. 在无反馈、无工具结果、无解析错误且没有 required completion tool 的分支直接设置现有 `Termination.ANSWERED_IN_PROSE`，删除一次性通用 prose nudge 及局部状态。
3. required completion tool 检查继续位于 prose 软完成之前，协作角色仍必须结构化提交。
4. 沿用结果渲染的默认关闭“正文已显示”标记，仅真实 TTY 流式路径开启，避免改变非流式调用方。

## Risks / Trade-offs

- [执行型任务的模型错误地只返回文字时不再自动纠偏] -> 终态仍明确为 `answered_in_prose`，不伪装为已验证完成；系统提示继续要求工具执行。
- [M47 的 Step/协作逻辑与旧分支不同] -> 以 M47 测试为主，逐分支移植，不覆盖相邻完整性逻辑。
- [终端去重隐藏正文] -> 只在正文已由真实流式输出显示时跳过最终重复渲染。

## Migration Plan

从已归档 `port-startup-logo-persistence` 后的最新 `main` 提交 `ebaca9caf91101d6a422278580afadc5a72019f0` 建立隔离实现分支；build 与 verify 的改动归属统一按该 `base_ref` 比较，不得使用当前旧分支 HEAD `3245a448` 或原始 M47 提交作为 diff 基准。旧 change 仍只作为已验证补丁和测试来源。先更新测试取得 RED，再移植 Step 与 CLI 最小差异并运行相关聚焦测试和全量回归。无数据迁移；回滚恢复 prose nudge 和旧渲染调用即可。

## Open Questions

无；技术语义已由旧 change 验证，实施阶段只处理 M47 冲突。

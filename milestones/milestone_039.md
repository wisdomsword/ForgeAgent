# 里程碑 M39: 协议正确性、协作终态投影与 Duo 验收契约

## 状态

- 状态: 已完成
- 日期: 2026-07-31
- 对应 ACTION_PLAN 行: M39
- 前置里程碑: [milestone_038](milestone_038.md)；M38 分发目标退役；规划基线可追溯至 M37
- 分发边界: PyPI、tag、push 和发布自动化继续暂停

## 目标与范围

M39 按三个顺序执行的 Comet change 完成：

1. `harden-loop-protocol-correctness`：Loop schema alias、双通道 tool-call 去重/冲突、空 prose、共享安全文本、English-first continuation、私有导入和 capability/receipt 投影日志加固。
2. `define-collaboration-stop-projection`：Task/Loop 到 Collaboration 的确定性终态映射，资源耗尽/需要输入/阻塞透传，以及内部执行 goal 与公开 handoff goal 分离。
3. `define-duo-acceptance-contract`：Duo 默认计划按产物、验证、文本三类 goal 交付形态生成可观察模板，保持单项 `goal` ID，并兼容旧 snapshot。

## 两轮自评

### 方案评审

- 第一轮确认三项 change 互相有序：先修协议基础，再稳定 Collaboration 终态边界，最后修改 Duo 验收语义；没有把条件候选 Memory、Rewrite/依赖或 HTTP 远程审批绑定混入主线。
- 第二轮确认不引入动态 LLM 拆解器、不扩大 Loop handoff、不修改发布目标；Duo 采用单项兼容模板而非三项动态计划，避免旧 Evaluator payload 失配。

### 收尾评审

- 发现并修复旧 Duo snapshot 会因新模板重算而被拒绝的问题，增加唯一 legacy plan 兼容路径。
- 发现并修复非字符串 goal 导致 raw `AttributeError` 越过 CollaborationError 边界的问题。
- 资源耗尽原因保留具体 reason；需要输入/阻塞才携带匹配 attention；公开 handoff 继续脱敏路径、secret 和 raw goal。

## 验收证据

- M39 全量 pytest: `2526 passed, 10 skipped`。
- Duo/Collaboration/HTTP focused: `390 passed`；Duo/store/tools focused 收尾: `117 passed`。
- Ruff check、Ruff format check、`uv build` 通过。
- `openspec validate --all --strict --no-interactive`: `30 passed, 0 failed`（归档前含 active change 的 strict 校验为 `31/31`）。
- 三个 Comet change 均已完成 build/verify 并归档；归档目录包含对应 proposal/design/spec/tasks 与验证报告。

## 条件候选

Memory 迁移、Rewrite/依赖门禁和 HTTP 远程动作审批绑定保持条件触发，未在 M39 中立项。任何未来公开分发需求都必须新建独立 change，不得恢复已撤销发布 change。

## 续接指引

读取本文件与 `ACTION_PLAN.md`。下一阶段优先从真实触发条件选择一个独立候选；没有触发条件时保持当前运行时基线，不主动搭建平台或迁移 Memory。

## Context

M47 的启动动画通过 Rich `Live(..., transient=True)` 渲染。transient 模式适合确认输入前的暂停，但初始化成功也复用了无参数 `stop()`，导致最终帧被清除。旧分支 change `2026-08-03-keep-startup-logo-visible` 已经实现并验证最小修复；本 change 的工作是把该行为移植到 M47，不合并旧分支的其他提交。

## Goals / Non-Goals

**Goals:**

- 初始化成功后在摘要和首个提示符上方保留恰好一次稳定 Logo。
- 确认暂停仍清除动态帧；异常、中断和非交互入口保持 M47 行为。
- 复用旧 change 的测试意图，在 M47 上重新取得 RED/GREEN 和回归证据。

**Non-Goals:**

- 不改变动画帧率、颜色、Logo 内容、启动摘要或终端能力判定。
- 不引入新依赖、配置、公共 API，也不移植无关旧分支提交。

## Decisions

1. 以 M47 为目标树，按旧 change 的文件级差异和测试逐项移植；遇到 M47 冲突时保留 M47 后续行为，只重建本 change 的验收语义。
2. 保留 `Live(transient=True)`。直接改为非 transient 会让每次确认暂停留下中间帧并产生重复输出。
3. 沿用 `StartupDisplay.stop(*, persist: bool = False)` 的最小方案：停止 Live 后，仅在成功点请求持久化，并以实例状态保证至多输出一次静态 Logo。
4. `pause()`、异常清理和 `finally` 继续使用默认不持久化；仅 MCP 初始化成功后的既有停止点传入 `persist=True`。

## Risks / Trade-offs

- [M47 已改变相邻启动流程] -> 不直接 cherry-pick 整个提交；先在 M47 建立失败测试，再移植最小行为。
- [成功停止后 `finally` 重复打印] -> 保留已渲染标记并测试幂等停止。
- [确认或失败路径误留 Logo] -> transient 不变，只有成功点显式持久化。

## Migration Plan

从 `main` M47 提交 `cc6472566cf13d5449b151f3047dcb8455db0d55` 建立隔离实现分支；build 与 verify 的改动归属统一按该 `base_ref` 比较，不得使用当前旧分支 HEAD `3245a448` 作为 diff 基准。移植测试与最小代码后运行 CLI 聚焦测试和全量回归。回滚只需撤销 `persist` 行为及对应文档，不涉及数据迁移。

## Open Questions

无；技术行为已由旧 change 验证，实施阶段只处理 M47 冲突。

# Brainstorm Summary

- Change: extract-cli-boundaries
- Date: 2026-07-31

## 确认的技术方案

采用“兼容 façade + 当前调用显式 bindings”。`forgeagent.cli` 保留 console 入口、历史导入和 monkeypatch 位置；纯 parser/config 函数从内部模块直接 re-export，协作、REPL 与 HTTP wrapper 在每次调用时从 `cli.py` 当前 globals 构造冻结 bindings，再调用对应内部实现。内部模块只依赖领域模块，不反向导入 `forgeagent.cli`。

按 parser/config、collaboration adapter、REPL、HTTP/client 顺序实施。目标文件为 `_cli_parser.py`、`_cli_collaboration.py`、`_cli_repl.py`、`_cli_http.py`；不再拆第五个模块，不引入通用容器、注册器或新依赖。

## 关键取舍与风险

- 不采用直接移动后批量修改测试路径，因为这会改变既有兼容替换点。
- 不采用 `CLIApplication`/service locator，因为本次没有新的生命周期模型，额外抽象不抵消复杂度。
- bindings 仅包含实际被历史测试替换或由 façade 拥有的依赖；简单值和稳定领域类型由内部模块直接导入。
- 原 `try/finally` 资源所有权随实现整体迁移，wrapper 不接管 close/cancel。
- 若性能、结构、依赖或行为硬阈值不满足，停止并回退 M41 提取，不修改阈值。

## 测试策略

- TDD：先添加结构、帮助哈希和 façade monkeypatch 契约测试，再逐边界移动。
- 每个边界迁移后运行对应 CLI/协作/REPL/HTTP 专项。
- 最终用原始命令复测 15 进程性能中位数、AST/行数/依赖、7 个帮助输出哈希、全量 pytest、Ruff、format、build、diff check 和 OpenSpec strict。
- 两轮最终自审覆盖循环依赖、globals 解析、关闭/取消、stdout/stderr、返回码、过度设计和既有工作区改动隔离。

## Spec Patch

无。OpenSpec delta spec 已覆盖六项门禁、四边界、兼容 façade、结构阈值和失败回退场景。

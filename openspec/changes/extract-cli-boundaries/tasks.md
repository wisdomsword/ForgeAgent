## 1. 重写门禁与兼容验证

- [x] 1.1 记录六项 Rewrite/Dependency 基线、阈值、证据、迁移步骤、回滚触发器和七组帮助输出哈希。
- [x] 1.2 增加确定性的结构与兼容测试，使任何违反 M41 边界或 façade 契约的提取立即失败。

## 2. 顺序边界提取

- [x] 2.1 将 parser/config 职责提取到 `_cli_parser.py`，保留 `forgeagent.cli` 导入与帮助文本字节，然后运行 parser/CLI 测试。
- [x] 2.2 将 collaboration adapter 职责提取到 `_cli_collaboration.py`，使用当前调用的 façade bindings，然后运行协作/CLI 测试。
- [ ] 2.3 将 REPL 状态与启动展示提取到 `_cli_repl.py`，使用当前调用的 façade bindings，然后运行 REPL/启动/CLI 测试。
- [ ] 2.4 将 HTTP/client 装配提取到 `_cli_http.py`，使用当前调用的 façade bindings，然后运行 HTTP/Loop/Collaboration/CLI 测试。

## 3. 阈值与回归验证

- [ ] 3.1 重新运行性能、结构、依赖、帮助哈希、聚焦 pytest、全量 pytest、Ruff、format、build、diff check 和 OpenSpec strict 验证。
- [ ] 3.2 对行为漂移、依赖环、隐藏 monkeypatch 断裂、资源所有权、过度设计、遗漏和阈值合规做两轮最终自审；修复并重新验证每个发现。
- [ ] 3.3 编写验证报告，更新 ACTION_PLAN 与 M41 里程碑追溯，归档 change，并确认分发动作仍排除在外。

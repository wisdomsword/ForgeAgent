## 1. 完整技术设计

- [x] 1.1 在 full design brainstorming 的第一项决策中明确 HTTP 是否仅返回相对引用（默认且当前范围）或扩大为受认证读取端点；随后确定 Task 证据模型、制品根目录与命名空间、容量上限、保留/清理策略、HTTP 引用有效期和向后兼容策略，并关闭 design.md 的开放问题。
- [x] 1.2 确认三个 port change 均已 verify/archive 并集成到 `main`，从该集成提交建立隔离实现分支并将本 change 的 `.comet.yaml.base_ref` 更新为该提交；不得从旧分支 HEAD 构建或与 filesystem-authority 并行修改重叠区域。
- [ ] 1.3 为 Single、纯 prose、失败/取消、trusted/restricted/container、内联/命名 Exec、HTTP、Loop、Duo、Triad 建立可执行失败测试。

## 2. Task 证据与程序制品

- [ ] 2.1 实现 Task 拥有的有界执行证据记录及 `TaskOutcome` 加法式投影，准确区分已解析、已尝试、成功、失败和未执行工具。
- [ ] 2.2 实现安全任务级程序制品持久化：宿主命名、语言扩展、原子写入、路径逃逸拒绝、容量边界和稳定失败原因。
- [ ] 2.3 将命名块与内联 Exec 统一接入“先持久化、后 backend dispatch”，覆盖 trusted、restricted 和 container，保证持久化失败时不执行代码。

## 3. 入口终态投影

- [ ] 3.1 在 CLI/REPL 终态一次性汇总工具、状态和本地程序路径；纯 prose 明确显示没有工具或程序执行，避免逐轮重复汇总。
- [ ] 3.2 在 HTTP terminal public view 中增加有界工具状态和安全相对制品引用，验证绝对路径、代码、参数、prompt、secret 和异常正文不会泄露。
- [ ] 3.3 在 LoopReport 与 CollaborationReport 中按迭代、角色和 attempt 有界聚合证据，覆盖 completed/stopped/failed/cancelled 及恢复场景。

## 4. 验证与交付

- [ ] 4.1 运行新契约的聚焦测试、HTTP/Loop/collaboration 回归、sandbox backend 测试、Ruff、全量测试和 OpenSpec strict 校验。
- [ ] 4.2 完成安全边界评审、向后兼容评审和 whole-change 代码审查，记录实际工具与程序制品路径的端到端验收证据。

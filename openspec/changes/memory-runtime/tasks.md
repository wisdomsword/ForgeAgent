## 1. 协议与确定性核心

- [x] 1.1 在 `src/forgeagent/protocol.py` 增加 `MemoryCandidate`、Memory 标记解析、正文剥离和结构化解析错误。
- [x] 1.2 新增 `src/forgeagent/memory.py`，实现有界候选校验、程序性/注入拒绝、稳定 Markdown 编解码、会话状态、项目原子替换和掩码渲染。
- [x] 1.3 增加候选 schema、准入矩阵、畸形条目、secret/注入拒绝、去重、冲突替换和写入失败保留的单元测试。

## 2. Task、身份与审计集成

- [x] 2.1 将 memory snapshot 注入 Task system prompt 组合，但不削弱显式 `system_prompt` 或 M15 身份信任边界。
- [x] 2.2 收集已完成 round 的候选并经配置的 MemoryManager 应用；暴露处理结果但不改变 Task 完成语义。
- [x] 2.3 通过现有核心 audit sink 写入最小披露的记忆生命周期事件，并补充审计断言。
- [x] 2.4 增加跨任务 mock replay 与项目重启测试，证明已接受记忆只在目标作用域可见，拒绝的投毒内容不会出现在后续 prompt。

## 3. CLI 与 headless 控制

- [ ] 3.1 接入由 REPL 持有的 session/project MemoryManager，实现 `/memory` 查看、`/remember` 提交和 `/reload` 刷新。
- [ ] 3.2 将 `--no-memory` 接入单次运行与 REPL 参数/配置链路，确保停用 manager 既不注入也不持久化候选。
- [ ] 3.3 保持 HTTP/headless 仅项目级语义，并增加无会话泄漏与停用记忆的请求路径回归测试。

## 4. 文档与验证资产

- [ ] 4.1 更新协议、CLI/配置、身份和威胁模型文档，记录记忆投毒边界与 Skill 分流。
- [ ] 4.2 增加记忆命中/未命中/拒绝 golden 候选并维持既有类别比例；在 runner 断言完成前保持候选与已验证 manifest 分离。
- [ ] 4.3 执行定向测试、全量 pytest、ruff、golden runner、OpenSpec strict 校验和 diff 检查；在 verify 前修复所有失败。

## 5. 评审与发布

- [ ] 5.1 评审范围、prompt 顺序、原子性、掩码和多入口一致性；修复发现并重跑受影响测试。
- [ ] 5.2 以精确命令证据和残余风险产出 M18 验证报告与里程碑记录。
- [ ] 5.3 执行 Comet verify，将 change 归档并同步主规格，合并分支到 `main`，保留无关用户工作区改动。

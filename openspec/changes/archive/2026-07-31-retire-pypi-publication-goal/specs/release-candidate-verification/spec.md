## MODIFIED Requirements

### Requirement: RC 说明与已知限制在历史记录中冻结
仓库 MUST 保留 `0.1.0` RC 工程验证记录，明确安装命令、已交付入口、验证口径和冻结的已知限制。记录 MUST 至少覆盖平台证据边界、真实模型验证边界、sandbox 安全边界、HTTP 暴露边界和协作 v1 边界；同时 MUST 明确包索引发布、正式 tag、远程 push 和发布自动化不在当前路线图。文档 MUST NOT 把未执行证据写成通过，也 MUST NOT 把外部发布动作写成待恢复门禁。

#### Scenario: 用户评估历史 RC
- **WHEN** 用户阅读 `0.1.0` RC 发布说明
- **THEN** 用户可区分已验证能力、opt-in 或未验证能力、已知限制，并看到分发目标已从当前路线图移除

#### Scenario: 限制被静默弱化
- **WHEN** 文档删除必需限制类别，或把历史、supplemental、配置态证据描述成当前正式验证
- **THEN** 发布文档合同测试失败并阻止 RC 记录通过

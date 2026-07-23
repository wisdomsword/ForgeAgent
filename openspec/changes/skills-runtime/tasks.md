## 1. Skill 核心与信任边界

- [ ] 1.1 先写失败测试覆盖 SKILL.md 五段校验、大小/数量上限、确定性诊断和用户/项目覆盖，再实现 `SkillDefinition` 与 `SkillRegistry`
- [ ] 1.2 先锁住既有 identity trust 行为，再提取通用内容摘要信任 helper，并覆盖项目 Skill 首次确认、摘要变化、headless 预批准和原子记录

## 2. 渐进加载与执行反馈

- [ ] 2.1 先写协议与工具测试，再实现 `SkillArgs`、只读 `Skill` 工具和 ToolRegistry 装配
- [ ] 2.2 将有界 Skill 目录接入 Task 系统提示词，验证全文不在初始上下文、按需读取后进入下一轮且不改变完成/确认/sandbox 语义
- [ ] 2.3 将 Skills 快照接入 CLI、`/reload` 和 HTTP Task 创建路径，覆盖会话替换、请求隔离与无确认降级

## 3. REPL 交互输入

- [ ] 3.1 添加并锁定 `prompt_toolkit` 依赖，实现由 `_SLASH_COMMAND_USAGE` 驱动的逐字符前缀候选和键盘选择
- [ ] 3.2 实现当前会话上下键历史，覆盖 TTY 增强路径、非 TTY fallback 及显式 `read_line` 兼容

## 4. Golden 与文档

- [ ] 4.1 增加离线 golden Skill 注入候选和渐进加载上下文体积断言，保持既有 20 项 verified core 不变
- [ ] 4.2 更新 README、SKILL.md 示例、文本协议、威胁模型与 ACTION_PLAN M19 状态

## 5. 评审与验证

- [ ] 5.1 运行受影响测试、完整 pytest、ruff、golden 20/20、OpenSpec strict、package build 与 diff check
- [ ] 5.2 完成两轮 whole-change 自审，立即修复发现的问题并重跑相关与完整验证
- [ ] 5.3 产出 M19 验证报告和里程碑文件，执行 Comet verify/archive 并提交主线可合并历史

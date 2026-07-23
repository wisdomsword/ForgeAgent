# 里程碑 M19: Skills Runtime

- 状态: 已完成
- 起止: 2026-07-23 ~ 2026-07-23
- 对应 ACTION_PLAN 行: M19（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_018](milestone_018.md)
- 技术设计: [2026-07-23-skills-runtime-design](../docs/superpowers/specs/2026-07-23-skills-runtime-design.md)
- 验证报告: [2026-07-23-skills-runtime-verify](../docs/superpowers/reports/2026-07-23-skills-runtime-verify.md)

## 目标与范围

交付验证严格、快照化、渐进加载的 Skills runtime：用户 Skill 可直接发现，项目 Skill
经独立内容摘要确认后才能覆盖；模型初始上下文只见有界目录，全文经只读 `Skill` 工具
按需进入反馈环。同时增强默认交互式 REPL：输入 `/` 后动态列出并逐字符过滤命令，
上下方向键回放当前会话历史。未增加远程安装、Skill 自动生成、管理命令或持久历史。

## 方案设计

- `SkillRegistry` 以不可变 session/request 快照承载确定性发现、固定五段校验、路径
  containment、secret masking 和目录上限。
- 项目 Skill 复用通用内容信任 helper，但使用独立 `skills-trust.json` 双摘要记录；
  未确认或记录不可用时安全降级到用户 Skill。
- `Task` 初始提示只注入 Skill 名称与 trigger；`SkillTool` 通过既有 Step feedback
  读取全文或指定分段，不改变两阶段完成、确认门或 sandbox 权限。
- CLI reload 原子替换 Skill 快照并保留 session Memory；HTTP 每个请求独立创建快照。
- prompt-toolkit 只用于默认 TTY reader，候选由 `_SLASH_COMMAND_USAGE` 单一来源驱动，
  历史仅驻留当前 REPL 进程。

## 子任务清单

- [x] 固定结构 Skill parser、边界校验与确定性 Registry
- [x] project-over-user 内容信任与原子记录
- [x] 只读 Skill 协议、工具和渐进反馈环
- [x] CLI/HTTP 快照、reload 与 REPL 输入增强
- [x] 文档、golden 候选、全量验证和 Comet 收尾

## 交付物清单

- [x] `src/forgeagent/skills.py` 与 identity 内容信任复用
- [x] Skill protocol/tool、Task/Step、CLI/HTTP 组合入口
- [x] prompt-toolkit 当前会话补全与历史
- [x] 单元、集成、golden 候选和安全回归测试
- [x] README、文本协议、威胁模型、ACTION_PLAN 与 OpenSpec 产物

## 三次评审

### 技术方案评审

- [x] 对照 M18 后续指引、ACTION_PLAN、proposal、两份 delta spec 和 Design Doc 复核范围。
- [x] 没有引入远程 Skill、额外 LLM 判定、workflow VM、持久历史或权限扩张。

### 代码评审

- [x] 每个实现任务均经过独立实现/规格审查与代码质量审查。
- [x] 两轮 whole-change 自审复核调用链、安全边界、入口一致性和无全文预加载。
- [x] 最终独立评审发现的两个测试证据缺口均已修复并复审通过。

### 验收评审

- [x] `1422 passed, 11 skipped`。
- [x] ruff check/format、golden `20/20`、OpenSpec strict、package build、diff check 全部通过。

## 遗留问题

- [ ] project Skill 变更需要重新确认 — 这是预期安全语义，不是缺陷；后续若需要批量管理，
  应另立 change，不扩张 M19。
- [ ] REPL 历史不跨进程保存 — 这是 M19 明确范围；只有实证需求出现时再设计持久历史。

## 续接指引

M19 已归档，功能分支 `codex/skills-runtime` 保留且未推送。下一阶段为 M20 Eval：在不
改变 M19 Skill 权限语义和 20 项 verified core 标准的前提下，增加分层指标聚合、趋势
记录与 opt-in 独立 Evaluator；继续保持离线 CI、secret masking 和请求/会话隔离。

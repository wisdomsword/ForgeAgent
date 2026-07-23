# Brainstorm Summary

- Change: skills-runtime
- Date: 2026-07-23

## 确认的技术方案

- `SKILL.md` 使用 `name`/`trigger` YAML front matter 与 `Steps`、`Failure branches`、`Completion criteria` 三个严格 Markdown 段，形成五段可验证结构。
- 新增有界、不可变快照式 `SkillRegistry`；用户级先加载，获信项目级后覆盖同名定义。只扫描直接子目录并拒绝越界 symlink。
- 初始系统提示词只追加按名称稳定排序的 `name — trigger` 目录；完整 Skill 只能由低风险只读 `Skill` 工具按名称加载，M17 截断时可按声明段继续读取。
- 项目 Skill 以规范项目路径、原始摘要和掩码后有效摘要进行独立持久信任；CLI 复用确认请求形状但使用 Skill 专用文案，HTTP 仅复用已批准摘要。
- Skill 步骤依靠现有 ToolRegistry、反馈环、确认门与 sandbox 执行，不建立第二套工作流解释器，不改变 Task 完成语义。
- 交互式默认 REPL reader 使用 `prompt_toolkit` 的逐字符 Completer 与内存 History；非 TTY 和显式 reader 保持原路径。

## 关键取舍与风险

- 选择 `prompt_toolkit` 而非 stdlib `readline`：前者完整支持持续候选菜单与键盘选择；新增依赖的成本低于自研 raw-mode 编辑器。
- 选择严格格式而非启发式 Markdown：牺牲宽松兼容，换取确定性解析、诊断和测试。
- 项目确认只展示有界元数据摘要，不代表内容安全；真实权限仍由工具确认与 sandbox 控制。
- 固定上限控制单文件、Skill 数、trigger 和目录字节；超限按名称稳定跳过，避免 M17 上下文预算退化。

## 测试策略

- TDD 覆盖格式、路径、上限、覆盖、摘要变化、headless 预批准、原子 trust 记录和无 Skill 等价性。
- Tool/Step mock replay 断言初始提示不含全文、按需调用后全文进入反馈、未知名称可恢复、失败分支与工具失败同轮可见。
- CLI/HTTP 测试覆盖 reload 原子替换、请求间无可变 Skill 状态、TTY 增强路径、非 TTY 与注入 reader 兼容。
- 离线 golden 新增有/无 Skill 行为差异候选，同时保持 verified core 20/20。
- 收尾运行完整 pytest、ruff、OpenSpec strict、package build、diff check 和两轮 whole-change 自审。

## Spec Patch

- `skills-runtime` 增加“完整结果被 M17 有界反馈截断后，可用同一 Skill 名称按 `steps`、`failure_branches`、`completion_criteria` 单段继续读取”的验收场景。

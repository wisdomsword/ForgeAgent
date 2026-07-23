# 里程碑 M19: Skills Runtime（含 Startup-Information 补充）

- 状态: 已完成（含归档后补充）
- 起止: 2026-07-23 ~ 2026-07-24
- 对应 ACTION_PLAN 行: M19（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_018](milestone_018.md)
- 技术设计: [2026-07-23-skills-runtime-design](../docs/superpowers/specs/2026-07-23-skills-runtime-design.md)
- 验证报告: [2026-07-23-skills-runtime-verify](../docs/superpowers/reports/2026-07-23-skills-runtime-verify.md)
- 人类验收: [2026-07-23-m19-human-smoke-design](../docs/superpowers/specs/2026-07-23-m19-human-smoke-design.md)
- OpenSpec 归档: [`2026-07-23-skills-runtime`](../openspec/changes/archive/2026-07-23-skills-runtime/)
- 补充技术设计: [2026-07-23-startup-information-design](../docs/superpowers/specs/2026-07-23-startup-information-design.md)
- 补充验证报告: [2026-07-23-startup-information-verify](../docs/superpowers/reports/2026-07-23-startup-information-verify.md)
- 补充 OpenSpec 归档: [`2026-07-23-startup-information`](../openspec/changes/archive/2026-07-23-startup-information/)

## 目标与范围

交付验证严格、快照化、渐进加载的 Skills runtime：用户 Skill 可直接发现，项目 Skill
经独立内容摘要确认后才能覆盖；模型初始上下文只见有界目录，全文经只读 `Skill` 工具
按需进入反馈环。同时增强默认交互式 REPL：输入 `/` 后动态列出并逐字符过滤命令，
上下方向键回放当前会话历史。未增加远程安装、Skill 自动生成、管理命令或持久历史。

归档后补充 Startup-Information：真实交互式 REPL 在初始化期间显示可清理的七色 ASCII
Logo，完成后只保留实际能力摘要；MCP 子进程 stderr 按 server generation 有界隔离并只
投影固定脱敏诊断；非 TTY、显式 reader、`run`/`serve` 保持无启动 UI，pipe quit 两路零字节。

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
- Startup UI 仍由 `cli.py` 单一展示层负责；`MCPManager` 只产生 immutable diagnostics，
  stderr sink 使用跨平台 blocking pipe reader 和有界 close join，不新增依赖或配置面。

## 子任务清单

- [x] 固定结构 Skill parser、边界校验与确定性 Registry
- [x] project-over-user 内容信任与原子记录
- [x] 只读 Skill 协议、工具和渐进反馈环
- [x] CLI/HTTP 快照、reload 与 REPL 输入增强
- [x] 文档、golden 候选、全量验证和 Comet 收尾
- [x] 无 API Key、无网络的一键本地人类验收
- [x] 修复补全观察期间误提交普通输入造成的假失败
- [x] 完成并归档 Startup-Information 补充 change
- [x] 真实 TTY 验证彩色/单色 Logo、available/optional MCP、确认暂停恢复、Ctrl-C 与 quit
- [x] 修复最终评审发现的 stderr close 无界等待、运行时诊断缺失和 Windows pipe 兼容问题

## 交付物清单

- [x] `src/forgeagent/skills.py` 与 identity 内容信任复用
- [x] Skill protocol/tool、Task/Step、CLI/HTTP 组合入口
- [x] prompt-toolkit 当前会话补全与历史
- [x] 单元、集成、golden 候选和安全回归测试
- [x] README、文本协议、威胁模型、ACTION_PLAN 与 OpenSpec 产物
- [x] `scripts/m19-skills-human-smoke.py` 与专项回归测试
- [x] `src/forgeagent/cli.py`、`src/forgeagent/mcp_manager.py` — 启动 UI、MCP 诊断与有界清理
- [x] `tests/test_cli_startup_blackbox.py`、MCP/CLI 回归与 `tests/mcp_fixture_server.py`
- [x] Startup-Information Design Doc、验证报告、主 specs 与 OpenSpec archive

## 三次评审

### 技术方案评审

- [x] 对照 M18 后续指引、ACTION_PLAN、proposal、两份 delta spec 和 Design Doc 复核范围。
- [x] 没有引入远程 Skill、额外 LLM 判定、workflow VM、持久历史或权限扩张。

### 代码评审

- [x] 每个实现任务均经过独立实现/规格审查与代码质量审查。
- [x] 两轮 whole-change 自审复核调用链、安全边界、入口一致性和无全文预加载。
- [x] 最终独立评审发现的两个测试证据缺口均已修复并复审通过。
- [x] 人类验收收尾复审发现导入时配置隔离、secret env 隔离、Ctrl-C 清理和额外输入假失败，均已补回归并修复。
- [x] 补充 change 的 whole-change 评审发现 stderr reader 无界 join 和运行时 failure 缺少固定诊断；修复后又发现 Windows `select()` 不兼容匿名 pipe，最终改为 blocking `os.read()` + 有界 join 并复审通过。

### 验收评审

- [x] 原 M19 完整回归 `1437 passed, 11 skipped`；人类验收焦点测试 `15 passed`。
- [x] 用户在真实 PTY 执行 `uv run --offline python scripts/m19-skills-human-smoke.py`，Skill 信任、渐进加载、`/reload`、斜杠补全和方向键历史六项全部 PASS。
- [x] Ruff check/format、golden `20/20`、OpenSpec strict、package build、diff check 全部通过。
- [x] 合并 Skills Runtime 与补充 change 后最终完整回归 `1504 passed, 11 skipped`；Startup 真实 PTY 覆盖动态/静态 Logo、`MCP 1/1`、optional failure、确认暂停恢复、`/mcp`、Ctrl-C 与 quit。
- [x] OpenSpec 全规格 `13/13`；Skills Runtime 与 Startup-Information 两个归档的 `.comet.yaml` 均为 `verify_result: pass`、`archived: true`。

## 遗留问题

- [ ] project Skill 变更需要重新确认 — 这是预期安全语义，不是缺陷；后续若需要批量管理，
  应另立 change，不扩张 M19。
- [ ] REPL 历史不跨进程保存 — 这是 M19 明确范围；只有实证需求出现时再设计持久历史。

## 续接指引

M19 Skills Runtime 与归档后 Startup-Information 补充均已合入 `main`，两个 OpenSpec
change 已归档，`milestones/latest` 继续指向本文件。下一个计划里程碑为 M20 Eval：在
不改变 M19 Skill 权限语义、启动输出契约和 20 项 verified core 标准的前提下，增加
分层指标聚合、趋势记录与 opt-in 独立 Evaluator；继续保持离线 CI、secret masking
和请求/会话隔离。

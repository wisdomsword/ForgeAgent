# 里程碑 M18: Memory Runtime

- 状态: 已完成
- 起止: 2026-07-23 ~ 2026-07-23
- 对应 ACTION_PLAN 行: M18（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_017](milestone_017.md)
- 技术设计: [2026-07-23-memory-runtime-design](../docs/superpowers/specs/2026-07-23-memory-runtime-design.md)
- 验证报告: [2026-07-23-memory-runtime-verify](../docs/superpowers/reports/2026-07-23-memory-runtime-verify.md)

## 目标与范围

交付显式记忆候选提取与准入、procedure 到 Skill 的分流、session/project 作用域、
`/memory`、`/remember`、`--no-memory`、项目冲突替换与原子持久化、投毒威胁模型和
离线 golden 候选。HTTP 不共享 session，M15 身份信任与 M17 context 行为保持不变。

## 方案设计

- 候选使用 `<!-- Memory: {...} -->` 文本协议，由 Pydantic 结构化解析；标记从展示正文剥离。
- `MemoryManager` 采用 bounded Markdown、固定准入规则、secret masking、受信项目路径
  校验、同目录临时文件与 `os.replace`。
- project Memory 只有经 M15 identity trust 批准的既有文件才可加载或覆盖；显式
  `system_prompt` 和 `--no-identity` 优先级不变。
- Task 只在 solved outcome 后应用候选，审计只记录 scope/kind/key/reason/task correlation。

## 子任务清单

- [x] 协议与确定性 Memory 核心
- [x] Task/Step/Identity/审计生命周期集成
- [x] CLI、REPL、HTTP 控制链路
- [x] 文档、golden 候选与全量回归
- [x] Comet build/verify/archive 收尾

## 交付物清单

- [x] `src/forgeagent/memory.py`、`protocol.py`、`task.py`、`step.py`
- [x] `src/forgeagent/cli.py` 与 Memory 协议提示资源
- [x] Memory、Task、CLI、Identity、golden 回归测试
- [x] 协议、README、威胁模型、ACTION_PLAN 与 OpenSpec 产物

## 三次评审

### 技术方案评审

- [x] 对照 proposal/design/spec 复核 scope、准入、原子性、HTTP 隔离和 context 边界。
- [x] 未引入向量检索、额外 LLM、团队作用域或 Skill 自动写入。

### 代码评审

- [x] 按用户要求完成两轮 whole-change 自审。
- [x] 修复审计 kind、symlink 越界、未信任覆盖、失败任务落盘、render 上限和 JSON brace 解析问题。
- [x] 受影响测试与完整回归均已重跑。

### 验收评审

- [x] `1375 passed, 11 skipped`。
- [x] ruff、golden `20/20`、OpenSpec strict、package build、diff check 全部通过。

## 遗留问题

- [ ] 注入检测仍是有限模式表 — 影响：无法覆盖所有自然语言投毒 — 计划：后续若出现实证缺口另立安全 change，不在 M18 引入模型判定。
- [ ] 记忆文件并发更新采用后写入者胜 — 影响：并发任务可能覆盖彼此不同步的快照 — 计划：仅在后续出现需求时设计锁或版本冲突协议。

## 续接指引

M18 已归档并合入 `main`。下一阶段为 M19 Skills：复用 Memory 的 procedure 分流原因，
设计显式 Skill 生命周期；继续保持无额外 LLM 判定、project-root 信任边界、原子文件
更新、HTTP 无 session 泄漏和 M17 有界 context 约束。

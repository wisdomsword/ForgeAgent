# 里程碑 M18: Memory Runtime

- 状态: 已完成
- 起止: 2026-07-23 ~ 2026-07-23
- 对应 ACTION_PLAN 行: M18（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_017](milestone_017.md)
- 技术设计: [2026-07-23-memory-runtime-design](../docs/superpowers/specs/2026-07-23-memory-runtime-design.md)
- 验证报告: [2026-07-23-memory-runtime-verify](../docs/superpowers/reports/2026-07-23-memory-runtime-verify.md)
- 事后 hotfix 1: `memory-result-feedback`（见
  [验证报告](../docs/superpowers/reports/2026-07-23-memory-result-feedback-verify.md)），
  归档 commit `4a07cac`
- 事后 hotfix 2: `memory-candidate-idempotency`（见
  [验证报告](../docs/superpowers/reports/2026-07-23-memory-candidate-idempotency-verify.md)），
  归档 commit `793bc47`

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

**归档后人工复测发现的两处偏差，已通过独立 hotfix change 修复并重新归档（不重开 M18）：**

- `memory-result-feedback`：`Task.run()` 曾丢弃 `MemoryManager.apply()` 的返回值，导致
  `--no-memory` 下模型口头声称"已记住"时 CLI 无法展示运行时真实的 `disabled` 结果；同次
  复测还发现 REPL 提示符处 Ctrl-C 会泄漏 traceback。修复：`TaskOutcome` 新增
  `memory_results` 字段并由 CLI 渲染权威结果；`read_line()` 边界单独捕获
  KeyboardInterrupt，任务执行期间的中断语义不变。
- `memory-candidate-idempotency`：模型在同一 Task 的工具自纠错多轮中重复发出完全相同的
  Memory 标记时，原实现按 round 顺序重复调用 `apply()`，产生重复的写入/审计/CLI 反馈；
  同次复测还发现固定协议把真实签名 `utils.set_state(key, value)` 误写成
  `utils.set_state(key=value)`，且未声明 `utils` 已注入无需 import，导致人工验收中出现
  ImportError/TypeError。修复：Task 按 `(scope, key)` 记录最近一次 `(kind, content)`，
  值未变化的重发只应用一次，值变化后再改回原值仍按出现顺序处理（保留
  `ruff → black → ruff` 式回退语义）；同时纠正 `runtime-identity` spec 中固定协议对
  `utils` API 的公开说明——这是对 M15 交付内容的回溯修正，不属于 M18 范围新增。

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
- [x] `docs/golden-tasks-seed.md` G401-G420 候选目录（20 个，维持既有 40/25/20/10/5%
  类别配比；候选目录未加入 verified manifest，不构成已验证声明）
- [x] hotfix 补充：`src/forgeagent/task.py`（`memory_results` 暴露 + 幂等去重）、
  `src/forgeagent/cli.py`（REPL Ctrl-C 处理）、
  `src/forgeagent/res/prompts/protocol.md`（`utils.set_state` 签名纠正）

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
- [x] hotfix 1（`memory-result-feedback`）：定向 `3 passed`，相关回归 `67 passed`，全量
  `1378 passed, 11 skipped`；ruff、`openspec validate --strict`、`git diff --check`、
  `uv build` 均通过。
- [x] hotfix 2（`memory-candidate-idempotency`）：定向 `3 passed`，相关回归
  `331 passed`，全量 `1381 passed, 11 skipped`，独立 golden `84 passed`；fast-forward
  合并 `main` 后复跑全量结果一致；ruff、`openspec validate --strict`、
  `git diff --check`、`uv build` 均通过。

## 遗留问题

- [ ] 注入检测仍是有限模式表 — 影响：无法覆盖所有自然语言投毒 — 计划：后续若出现实证缺口另立安全 change，不在 M18 引入模型判定。
- [ ] 记忆文件跨 Task/跨进程并发更新采用后写入者胜、v1 不加文件锁 — 影响：两个并发任务
  可能覆盖彼此不同步的项目快照 — 计划：仅在后续出现实证需求时设计锁或版本冲突协议。
  （注：同一 Task 内重复候选的幂等语义已由 hotfix 2 `memory-candidate-idempotency`
  解决，不再是本条覆盖范围。）

## 续接指引

M18 已归档并合入 `main`。下一阶段为 M19 Skills：复用 Memory 的 procedure 分流原因，
设计显式 Skill 生命周期；继续保持无额外 LLM 判定、project-root 信任边界、原子文件
更新、HTTP 无 session 泄漏和 M17 有界 context 约束。

# Comet Design Handoff

- Change: extract-cli-boundaries
- Phase: design
- Mode: compact
- Context hash: ee0a43b238e21a1b9002ea1d4072168589efa20c55f3f0fba38209f3cbb67f62

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/extract-cli-boundaries/proposal.md

- Source: openspec/changes/extract-cli-boundaries/proposal.md
- Lines: 1-28
- SHA256: ba6b36eb279655a5e7c45b2f0bfb45ddeeaf5c9955eba9f394ee136d15efb0ac

```md
## Why

`src/forgeagent/cli.py` 已增长到 3226 行、129220 字节并承担 parser/config、协作装配、REPL、HTTP/client 等多类职责，使评审、故障定位和局部验证成本持续上升。M41 在不改变任何 CLI、HTTP 或运行时契约的前提下，先用六项 Rewrite/Dependency 门禁建立退出条件，再做可回退的职责提取。

## What Changes

- 建立 performance、reliability、maintenance cost、compatibility、team capability、migration/rollback risk 六项基线、阈值、证据、迁移和回滚触发器。
- 将 parser/config、collaboration adapter、REPL、HTTP/client 代码提取到职责明确的内部模块，`forgeagent.cli` 继续作为兼容 façade 和 console-script 入口。
- 保持命令、参数、默认值、帮助文本、退出码、stdout/stderr、HTTP 请求/响应、既有导入与测试替换点不变。
- 使用按边界执行的测试和提交逐步迁移；任一硬阈值不满足时停止并回退 M41 自身提取，不触碰进入 M41 前的用户工作区改动。
- 不引入新依赖、语言、配置面、运行时能力、数据迁移或发布目标。

## Capabilities

### New Capabilities

- `cli-boundary-maintainability`: 定义 CLI 内部边界、兼容 façade、六项 Rewrite/Dependency 退出门禁和可回退验证要求。

### Modified Capabilities

无。现有 CLI、REPL、HTTP、Loop、Collaboration 和审计行为规格均保持不变。

## Impact

- 代码：`src/forgeagent/cli.py` 及新增的 `src/forgeagent/_cli_*.py` 内部模块。
- 测试：既有 CLI/协作/HTTP 测试继续作为兼容门禁，并新增结构与基线验证。
- 文档：新增 M41 六项基线、技术设计、实施计划、验证报告和里程碑记录。
- 依赖/API/数据：无新增依赖；无 public API、schema、配置或持久化数据变化。

```

## openspec/changes/extract-cli-boundaries/design.md

- Source: openspec/changes/extract-cli-boundaries/design.md
- Lines: 1-67
- SHA256: 03df0f9ddc3a2e7d5fd51bfeb6dee8dede786074135f6d8891e82ea97b2910f4

```md
## Context

`forgeagent.cli` 既是 console-script 入口，也是历史测试和内部调用方的兼容导入面。当前模块把参数解析、配置装载、协作运行装配、REPL 状态机、HTTP 服务装配及若干展示工具放在同一文件中。直接重命名或移动函数会破坏大量 `forgeagent.cli.<name>` monkeypatch 点，因此本次不能把“文件拆小”误当成“兼容已保持”。

六项 Rewrite/Dependency 基线和停止阈值记录在 `docs/evaluation/m41/rewrite-dependency-baseline.md`。它们是实施许可的一部分，不是完成后补写的说明。

## Goals / Non-Goals

**Goals:**

- 将 parser/config、collaboration adapter、REPL、HTTP/client 分离为私有内部模块。
- 让 `forgeagent.cli` 收敛为稳定入口、兼容 façade 和顶层命令分派。
- 保留历史导入、monkeypatch、输出、退出码、HTTP schema、资源关闭与安全边界。
- 用按边界提交和门禁让每一步可以单独定位与回退。

**Non-Goals:**

- 不增加或删除命令、选项、配置键、HTTP 字段或运行模式。
- 不重写 Task、Loop、Collaboration、MCP、Memory、Skills 或 HTTP service 领域逻辑。
- 不引入 DI 框架、插件注册器、全局 service locator、代码生成或新依赖。
- 不修改进入 M41 前已有的用户工作区改动，不恢复任何分发目标。

## Decisions

### 1. 保留 `forgeagent.cli` 作为兼容 façade

对无可变依赖的纯函数，`cli.py` 可以直接 re-export。对依赖测试替换点或生命周期所有权的入口，`cli.py` 保留薄 wrapper，并把当次调用需要的 class/callback/value 显式传给内部实现。这样 monkeypatch 仍命中 `forgeagent.cli`，内部模块不反向导入 `cli.py`，避免循环依赖。

不采用“移动后更新全部测试 monkeypatch 路径”，因为它会改变现有测试契约并掩盖第三方内部调用回归；也不采用 `sys.modules` alias 或动态代理，因为其行为隐式且排障成本更高。

### 2. 四个单向内部边界

- `_cli_parser.py`：`argparse` parser 构建、严格 JSON/evaluation 命令解析及纯配置值解析；不得启动网络、MCP、Task 或 HTTP server。
- `_cli_collaboration.py`：Single/Duo/Triad CLI adapter；只负责已有 Runner/Task 的装配和公开报告渲染，不拥有领域状态迁移。
- `_cli_repl.py`：REPL 会话状态机、启动展示和命令调度；通过显式 bindings 调用 `cli.py` 暴露的既有执行/命令函数。
- `_cli_http.py`：HTTP runtime 配置和服务装配；通过显式 bindings 使用现有 `http_server`、`TaskService`、Loop/Collaboration 组件，不改变 HTTP domain model。

内部模块可以依赖领域模块，但不得互相形成环或导入 `forgeagent.cli`。`cli.py` 负责从当前模块全局值构造 bindings，因此历史 monkeypatch 继续生效。

### 3. 按风险从低到高迁移

顺序固定为 parser/config → collaboration adapter → REPL → HTTP/client。每步先补/运行本边界回归，再移动实现并复测；失败只回退当前 M41 步骤。最后才评估六项阈值，未达标则停止并回退 M41 提取，不以放宽阈值宣称完成。

### 4. 性能和结构门禁使用同口径复测

性能使用独立 Python 进程的中位数，避免单进程模块缓存伪造改善。结构用 AST 和文件字节统计；兼容用 7 个帮助入口字节哈希、既有 pytest 和旧导入/monkeypatch 回归。不得在实施后更换采样方法或删除失败场景。

## Risks / Trade-offs

- [显式 bindings 增加少量样板] → 只为真实 monkeypatch/lifecycle 边界建冻结 dataclass，不建立通用容器。
- [机械迁移可能改变函数 globals 的解析位置] → façade wrapper 在每次调用时从 `cli.py` 当前 globals 构造 bindings，并用现有 monkeypatch 测试验证。
- [HTTP/REPL 资源关闭顺序漂移] → 保留原 `try/finally` 所有权，增加/保留 close、cancel、startup failure 专项测试。
- [性能受机器噪声影响] → 比较 15 个独立进程的中位数，20% 作为材料性退化阈值；超阈值后只允许同口径干净复测一次。
- [为了行数阈值产生过度拆分] → 新模块固定为四个边界，最大 900 行；禁止再建 manager/factory/registry 层。

## Migration Plan

1. 固化基线、帮助哈希和结构契约。
2. 提取 parser/config，保持 `build_parser` 等旧名称可导入。
3. 提取 collaboration adapter，并通过 façade bindings 保持替换点。
4. 提取 REPL 会话状态机与启动展示，保留 slash handler 和执行入口契约。
5. 提取 HTTP/client 装配，保留服务错误投影、关闭和返回值。
6. 执行六项复测；任一硬阈值失败则回退 M41 提取提交并保留基线文档作为停止证据。

## Open Questions

无。用户已授权在决策点进行两轮自审后采用推荐方案；本设计选择单 change、branch 隔离、TDD 和 standard review，不引入子代理。

```

## openspec/changes/extract-cli-boundaries/tasks.md

- Source: openspec/changes/extract-cli-boundaries/tasks.md
- Lines: 1-17
- SHA256: 42d7e997aa70702deefeada9c63f2273ce4759c8ae5b3cc4e857eba1a818bdf0

```md
## 1. 重写门禁与兼容验证

- [ ] 1.1 记录六项 Rewrite/Dependency 基线、阈值、证据、迁移步骤、回滚触发器和七组帮助输出哈希。
- [ ] 1.2 增加确定性的结构与兼容测试，使任何违反 M41 边界或 façade 契约的提取立即失败。

## 2. 顺序边界提取

- [ ] 2.1 将 parser/config 职责提取到 `_cli_parser.py`，保留 `forgeagent.cli` 导入与帮助文本字节，然后运行 parser/CLI 测试。
- [ ] 2.2 将 collaboration adapter 职责提取到 `_cli_collaboration.py`，使用当前调用的 façade bindings，然后运行协作/CLI 测试。
- [ ] 2.3 将 REPL 状态与启动展示提取到 `_cli_repl.py`，使用当前调用的 façade bindings，然后运行 REPL/启动/CLI 测试。
- [ ] 2.4 将 HTTP/client 装配提取到 `_cli_http.py`，使用当前调用的 façade bindings，然后运行 HTTP/Loop/Collaboration/CLI 测试。

## 3. 阈值与回归验证

- [ ] 3.1 重新运行性能、结构、依赖、帮助哈希、聚焦 pytest、全量 pytest、Ruff、format、build、diff check 和 OpenSpec strict 验证。
- [ ] 3.2 对行为漂移、依赖环、隐藏 monkeypatch 断裂、资源所有权、过度设计、遗漏和阈值合规做两轮最终自审；修复并重新验证每个发现。
- [ ] 3.3 编写验证报告，更新 ACTION_PLAN 与 M41 里程碑追溯，归档 change，并确认分发动作仍排除在外。

```

## openspec/changes/extract-cli-boundaries/specs/cli-boundary-maintainability/spec.md

- Source: openspec/changes/extract-cli-boundaries/specs/cli-boundary-maintainability/spec.md
- Lines: 1-53
- SHA256: da3c9e29303d32ff74386ebcfebbed140159d8f595447484fa1a63044a99783c

```md
## ADDED Requirements

### Requirement: CLI extraction is gated by six measured dimensions

M41 MUST record baseline, threshold, evidence, migration, and rollback trigger for performance, reliability, maintenance cost, compatibility, team capability, and migration/rollback risk before implementation. If any hard threshold cannot be met with the original measurement method, the extraction MUST stop and M41 implementation changes MUST be rolled back without altering pre-existing workspace changes.

#### Scenario: All six gates are measurable
- **WHEN** implementation begins
- **THEN** each metric has a concrete baseline, threshold, evidence source, migration step, and rollback trigger recorded in the M41 baseline

#### Scenario: A hard threshold fails
- **WHEN** a final same-method measurement still exceeds a threshold or detects a contract regression
- **THEN** M41 extraction changes are not accepted and the pre-M41 CLI implementation remains authoritative

### Requirement: CLI responsibilities have four internal boundaries

ForgeAgent SHALL separate parser/config, collaboration adapter, REPL, and HTTP/client responsibilities into private internal modules while keeping `forgeagent.cli` as the console entry point and compatibility façade. Internal boundary modules MUST NOT import `forgeagent.cli`, form dependency cycles, introduce a general dependency-injection framework, or own domain state that belongs to Task, Loop, Collaboration, MCP, Memory, Skills, or HTTP service models.

#### Scenario: A maintainer locates a CLI responsibility
- **WHEN** the maintainer inspects parser/config, collaboration adapter, REPL, or HTTP/client assembly
- **THEN** the responsibility is implemented in the corresponding named internal boundary and exposed through `forgeagent.cli` only where compatibility requires it

#### Scenario: Runtime dependencies are inspected
- **WHEN** the post-extraction dependency tree is compared with the baseline
- **THEN** no runtime dependency, framework, registry, or generated-code layer has been added for the extraction

### Requirement: Existing CLI and HTTP behavior remains unchanged

The extraction MUST preserve command names, option names, defaults, parser behavior, help bytes, stdout/stderr routing, exit codes, existing `forgeagent.cli` imports, supported monkeypatch locations, HTTP request/response shapes, cancellation semantics, and resource cleanup behavior. It MUST NOT add configuration, persistence, data migration, publication, tag, push, or package-index behavior.

#### Scenario: Existing help commands run
- **WHEN** the seven recorded top-level and subcommand help invocations are executed after extraction
- **THEN** their exit codes and stdout/stderr SHA-256 values match the pre-extraction baseline byte for byte

#### Scenario: Existing boundary tests run
- **WHEN** CLI, collaboration integration, HTTP, startup, and full regression tests execute
- **THEN** all previously passing scenarios still pass and M41 introduces no additional skip

#### Scenario: A test replaces a CLI dependency
- **WHEN** an existing test monkeypatches a supported `forgeagent.cli` class, callback, factory, or helper before invoking a façade entry point
- **THEN** the extracted implementation uses that replacement for the current call just as the pre-extraction implementation did

### Requirement: Extraction remains bounded and reversible

The final `cli.py` MUST contain no more than 1800 lines, each new boundary module MUST contain no more than 900 lines, and the runtime direct dependency count MUST remain at eight. Migration MUST proceed in the order parser/config, collaboration adapter, REPL, HTTP/client with targeted verification at each boundary, and each boundary MUST remain independently reviewable and revertible.

#### Scenario: Structural threshold is measured
- **WHEN** the final AST and file statistics are generated
- **THEN** `cli.py`, every extracted module, and the dependency tree satisfy the recorded maintenance thresholds

#### Scenario: One boundary regresses behavior
- **WHEN** targeted verification fails after a boundary extraction
- **THEN** that boundary is corrected or its M41 extraction is reverted before the next boundary begins

```

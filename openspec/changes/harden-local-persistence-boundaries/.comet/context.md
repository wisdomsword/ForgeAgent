# Comet Design Handoff

- Change: harden-local-persistence-boundaries
- Phase: design
- Mode: compact
- Context hash: 61f2972623be6c8c69280a3a08682cdc1ce2cddf0a481ed3f803dfc764819ee7

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/harden-local-persistence-boundaries/proposal.md

- Source: openspec/changes/harden-local-persistence-boundaries/proposal.md
- Lines: 1-39
- SHA256: 2f87818aa9b3d1f07675ed875ce26453a54addd755a4b26c90b1db256654cea5

```md
## Why

ForgeAgent 的三个本地持久化边界仍依赖“先检查、后按 pathname 打开”或仅进程内锁：
FileWrite 可在校验与写入之间遭遇 symlink 替换，项目 Memory 的并发写入可能丢失不同 key，
Loop checkpoint 的 revision 检查也不能阻止两个进程同时提交同一旧 revision。它们会削弱
既有项目根目录边界和耐久状态契约，因此需要在不扩展产品能力的前提下完成加固。

## What Changes

- FileWrite 在 canonical containment 校验后，以 descriptor-relative、`O_NOFOLLOW` 的方式逐级
  打开父目录和最终文件，拒绝校验后发生的 symlink 替换。
- 项目 Memory 使用同目录稳定 lock file 和标准库跨进程排他锁，将“重读最新磁盘状态、合并
  候选、原子替换”收敛为一个临界区；不同 key 不再互相覆盖，同 key 保持后锁获得者胜。
- Loop checkpoint 为每个 Loop ID 使用稳定 lock file，将 create/save 的存在性或 revision
  校验与原子替换放入同一跨进程临界区，使 stale revision 只能有一个提交成功。
- 补充并发、symlink 竞态、锁失败和兼容性回归测试，并更新威胁模型与公开规格。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-approval`: FileWrite 的项目根目录约束从静态 symlink 防护扩展到 descriptor-relative
  最终打开，拒绝校验后的 symlink 替换。
- `runtime-memory`: 项目 Memory 的冲突替换扩展为跨进程 read-modify-write 串行化，不同 key
  并发写入必须合并而不是丢失。
- `loop-execution`: checkpoint create/save 的 revision 契约扩展为跨进程原子 CAS，拒绝同一旧
  revision 的重叠提交。

## Impact

- 主要修改 `src/forgeagent/tools.py`、`memory.py`、`loop.py` 及对应测试。
- 使用 Python 标准库和 POSIX descriptor/locking 能力，不新增依赖、配置项、公共命令或数据
  schema 字段。
- 不处理分布式锁、网络文件系统一致性、exactly-once 外部副作用、Windows 新平台支持、
  CollaborationStore 跨进程协调或通用持久化框架。

```

## openspec/changes/harden-local-persistence-boundaries/design.md

- Source: openspec/changes/harden-local-persistence-boundaries/design.md
- Lines: 1-84
- SHA256: b18980448ae82f683669f760de6cf560a6ae4d5bd3464842dfb248fae29e0fe7

[TRUNCATED]

```md
## Context

三个边界都已使用同目录临时文件加 `os.replace`，但原子替换只保证单次写入不撕裂，并不
保证前置决策与写入之间的原子性：FileWrite 的 containment 检查与 pathname open 分离；
Memory 基于进程启动时的快照重写整个文件；Loop 的 revision 比较只受对象内
`threading.RLock` 保护。目标平台已有 POSIX descriptor 和 `fcntl.flock`，项目也已有
descriptor-relative、`O_NOFOLLOW`、`fsync` 的 store 模式。

## Goals / Non-Goals

**Goals:**

- FileWrite 的最终写入不得跟随校验后新出现的 symlink，父目录替换也必须失败关闭。
- 项目 Memory 的跨进程更新必须在锁内重读并合并最新磁盘状态。
- Loop create/save 的存在性或 revision 校验与替换必须在同一跨进程锁内完成。
- 保持现有公共 API、固定错误文本、文件格式和原子替换语义。

**Non-Goals:**

- 不提供分布式锁、网络文件系统强一致、Windows 新平台支持或锁超时配置。
- 不解决 Loop 外部副作用 exactly-once，也不扩展 CollaborationStore。
- 不新增依赖、通用 storage/lock abstraction、数据库或后台守护进程。

## Decisions

### 1. FileWrite 使用逐组件 descriptor-relative open

从 canonical `allowed_root` 以 `O_DIRECTORY|O_NOFOLLOW` 打开根目录 descriptor；规范化相对
路径并拒绝 `..`、空目标和 root 本身。逐级用 `dir_fd` 打开既有父目录，缺失父目录保持
当前“不自动 mkdir”的行为；最终文件用 `O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW` 打开并在
descriptor 上写入。写入前后验证 root directory binding，任何 symlink、非目录、目录替换
或最终目标非普通文件均返回现有固定失败结果。

未采用“再次 realpath/lstat”，因为检查与最终 open 之间仍有竞态；未采用临时文件替换，
因为 FileWrite 当前公开语义允许覆盖目标，而 descriptor-relative final open 已足够封闭本次
竞态且 diff 更小。

### 2. Memory 使用稳定 lock file 串行化 read-modify-write

项目 Memory 写入前打开 `.forgeagent/.MEMORY.lock`，使用 `fcntl.flock(LOCK_EX)`。锁内从磁盘
重新解析最新合法 project entries，再应用单个候选并检查条目/字节上限，最后沿用同目录临时
文件加 `os.replace`。不同 key 因重读而合并；同 key 由后获得锁的候选覆盖。成功后更新当前
manager 的 `_project`；锁/open/read/write 失败继续返回 `persistence_error`，不修改内存快照。

采用 advisory lock 而不是 revision 字段，避免改变人类可编辑的 MEMORY.md 格式。锁文件固定、
私有权限、拒绝 symlink，并只在写入临界区持有。

### 3. Loop 使用每 ID lock file 实现跨进程 CAS

在既有 `.forgeagent/loops` directory fd 下为每个 Loop ID 使用 `.<id>.lock`，以
`O_CREAT|O_NOFOLLOW` 和私有权限打开并获取 `LOCK_EX`。`create` 的“不存在检查+写入”和
`save` 的“load current+expected_revision 比较+写入”全部在该锁内执行。锁文件不删除，避免
unlink 后不同进程锁住不同 inode；checkpoint JSON schema 和 revision 字段不变。

采用每 ID 锁而不是全目录锁，使不同 Loop 仍可并行；不依赖 `threading.RLock` 提供跨进程
保证，后者只继续保护同一 store 对象的线程安全。

### 4. 失败语义保持固定且 fail closed

FileWrite 不披露路径或异常。Memory 锁/重读/替换失败映射为现有
`persistence_error/project_write_failed`。Loop 锁或 CAS 失败映射为
`LoopCheckpointError`，Checkpoint tool 继续返回 `Checkpoint save failed`。所有 descriptor
在异常路径关闭，临时文件继续尽力清理。

## Risks / Trade-offs

- `flock` 是 advisory 且依赖本地 POSIX 文件系统 → 只约束 ForgeAgent 进程；文档不承诺对
  绕过协议的外部编辑器或不可靠网络文件系统提供强一致。
- FileWrite 逐组件 open 增加少量平台代码 → 直接复用现有 store 的 `O_NOFOLLOW`/directory-fd
  模式并用集中测试覆盖，不抽象通用 filesystem manager。
- 稳定 lock file 会留在 `.forgeagent` 目录 → 文件有界且不含业务内容；不删除以保证 inode
  锁身份稳定。
- Memory 锁内重读可能遇到手工写入的畸形文件 → 沿用现有“忽略畸形条目、保留合法条目”
  规则，且候选写入不会把未解析内容重新保存。

## Migration Plan

无需数据迁移。现有 MEMORY.md 和 Loop JSON 保持兼容；首次写入按需创建稳定 lock file。
回滚代码后遗留 lock file 无行为影响。实现按测试先行分别落地 FileWrite、Memory、Loop，
最后更新主规格和威胁模型并运行全量门禁。

```

Full source: openspec/changes/harden-local-persistence-boundaries/design.md

## openspec/changes/harden-local-persistence-boundaries/tasks.md

- Source: openspec/changes/harden-local-persistence-boundaries/tasks.md
- Lines: 1-23
- SHA256: a9164a9dc7deecfa55d31e411f37f1b2d85b9fb5a2d18f41a9ade6b2200401f2

```md
## 1. FileWrite descriptor 边界

- [ ] 1.1 新增失败测试，覆盖最终目标 symlink 替换、父目录 symlink 替换、根目录绑定替换和固定失败信息不变。
- [ ] 1.2 实现基于 descriptor 的 `O_NOFOLLOW` 父目录遍历与最终写入，不新增依赖或公共 API 变更。
- [ ] 1.3 运行 FileWrite、headless 确认、golden 和威胁模型专项回归。

## 2. 项目 Memory 跨进程更新

- [ ] 2.1 新增失败测试，以两个独立 manager/进程覆盖不同 key 合并、同 key 后锁获得者胜、不安全 lock path 和锁/写入失败回滚。
- [ ] 2.2 实现稳定私有的 Memory lock file，以及锁内磁盘重载、准入/限额检查、合并和原子替换。
- [ ] 2.3 运行 Memory、CLI reload、identity 和 audit 专项回归。

## 3. Loop checkpoint 跨进程 CAS

- [ ] 3.1 新增失败测试，覆盖同 revision 重叠保存、重叠创建、不安全 lock file 和不同 Loop ID 并行。
- [ ] 3.2 实现每个 Loop 独立的稳定私有 lock file，以及锁内 create/save 校验和原子替换。
- [ ] 3.3 运行 Loop store、runner、HTTP 和 collaboration resume 专项回归。

## 4. 契约与完成门禁

- [ ] 4.1 更新 `docs/threat-model.md` 和受影响的公开文档，说明增强后的本地文件系统保证以及 advisory lock/网络文件系统残余边界。
- [ ] 4.2 运行格式化、Ruff、专项测试、完整 pytest、golden 20/20、包构建、OpenSpec strict 和 `git diff --check`。
- [ ] 4.3 完成两轮最终自审和独立代码审查；修复全部 Critical/Important 发现并记录验证报告。

```

## openspec/changes/harden-local-persistence-boundaries/specs/loop-execution/spec.md

- Source: openspec/changes/harden-local-persistence-boundaries/specs/loop-execution/spec.md
- Lines: 1-28
- SHA256: 927aeb8c28bbf4b737ea06e507523a85c0e49cdd7d0d4ca3fe6b170d3e1eebc5

```md
## MODIFIED Requirements

### Requirement: Loop checkpoint 是版本化、原子且有界的耐久状态
Loop SHALL 将 schema 版本、Loop 身份、原始目标、预算配置、累计预算、迭代计数、连续失败数、已完成条目、未解问题、下轮交接信息、最近安全失败摘要和终态写入 checkpoint。checkpoint MUST 位于允许根目录内，MUST 使用原子替换写入，MUST 拒绝符号链接逃逸、未知字段、超限内容、无效状态组合和不支持的 schema 版本。每个 Loop ID 的 create 与 save MUST 使用稳定 lock file 的跨进程排他锁，将存在性或 expected revision 校验与原子替换纳入同一临界区；同一旧 revision 的重叠提交最多一个成功。

#### Scenario: 模型提交进度 checkpoint
- **WHEN** Loop 专用 `Checkpoint` 工具收到合法的已完成条目、未解问题和交接信息
- **THEN** 系统在返回工具成功反馈前原子持久化新状态，并保留此前已提交完成条目

#### Scenario: 进程在 Task 中途终止
- **WHEN** 模型已成功调用 `Checkpoint`，随后进程在当前 Task 返回前被终止
- **THEN** checkpoint 仍包含已提交进度，恢复提示明确要求跳过这些完成条目

#### Scenario: checkpoint 写入失败
- **WHEN** checkpoint 目录不可写、目标发生路径逃逸、lock file 不安全、加锁失败或原子替换失败
- **THEN** `Checkpoint` 工具返回结构化失败，Loop 不声称进度已持久化，且失败可进入现有 Task 反馈环

#### Scenario: checkpoint 内容或版本无效
- **WHEN** resume 读取到未知 schema、额外字段、超限文本、无效计数或互相矛盾的终态
- **THEN** 系统在调用模型或工具前拒绝恢复，并保留原文件不变

#### Scenario: 同一旧 revision 跨进程重叠提交
- **WHEN** 两个进程都读取 revision N 并以 `expected_revision=N` 提交不同 checkpoint
- **THEN** 第一个锁内提交写入 revision N+1，第二个锁内重读后收到 stale revision 错误且不得覆盖第一份状态

#### Scenario: 不同 Loop ID 并行提交
- **WHEN** 两个进程同时保存不同 Loop ID
- **THEN** 它们使用不同稳定 lock file，不因全目录锁而互相串行化

```

## openspec/changes/harden-local-persistence-boundaries/specs/runtime-memory/spec.md

- Source: openspec/changes/harden-local-persistence-boundaries/specs/runtime-memory/spec.md
- Lines: 1-24
- SHA256: 37c372bd6cca93348f23b7e077e2c514eabc582f6eab6ceb0b88dd864d44b5c3

```md
## MODIFIED Requirements

### Requirement: 项目记忆原子持久化与冲突替换
项目级记忆 MUST 以稳定的 Markdown 条目格式写入 MEMORY.md，并 MUST 通过同目录临时文件加 `os.replace` 原子替换；写入失败 MUST 保留旧文件并返回结构化错误。项目级 read-modify-write MUST 由同目录稳定 lock file 的跨进程排他锁串行化，并 MUST 在锁内重新加载最新合法条目后再应用候选。相同 key 的新候选 SHALL 由后获得锁的写入替换旧条目，不同 key 的重叠写入 SHALL 合并而不得互相丢失；替换和拒绝都 MUST 可由审计记录追踪。加载时畸形条目 MUST 被忽略并输出脱敏诊断，不得执行其内容。

#### Scenario: 相同 key 冲突替换
- **WHEN** 两个进程基于相同旧快照依次获得锁，并分别为同一 key 写入 `vim` 与 `nvim`
- **THEN** MEMORY.md 只保留后获得锁的 `nvim` 条目，并记录相应 replaced 结果

#### Scenario: 不同 key 并发写入合并
- **WHEN** 两个进程基于相同旧快照分别写入不同 project key
- **THEN** 后获得锁的进程在锁内重读前一提交，最终 MEMORY.md 同时包含两个 key

#### Scenario: 原子写入失败
- **WHEN** lock file 打开、加锁、临时文件创建或替换失败
- **THEN** 旧 MEMORY.md 保持字节不变，任务继续运行并返回 persistence_error

#### Scenario: 畸形条目隔离
- **WHEN** MEMORY.md 包含不符合受控条目格式的 Markdown 或注入文本
- **THEN** 该条目不注入模型上下文，其余合法条目仍可加载

#### Scenario: Memory lock path is unsafe
- **WHEN** 稳定 lock file 是 symlink 或不能以安全私有文件打开
- **THEN** 项目候选返回 persistence_error，MEMORY.md 和当前 manager 的 project 快照均不改变

```

## openspec/changes/harden-local-persistence-boundaries/specs/tool-approval/spec.md

- Source: openspec/changes/harden-local-persistence-boundaries/specs/tool-approval/spec.md
- Lines: 1-32
- SHA256: 991307dbceb9611a3a69b1dfc8c6c245fd9f35695f008668c2546db5ca93d2fc

```md
## MODIFIED Requirements

### Requirement: File tool path boundaries are root-safe and minimally disclosing
ForgeAgent MUST evaluate canonical WebFetch artifact and file-tool targets with a containment predicate that accepts the root itself and all real descendants, including when `allowed_root` is the filesystem root, and MUST NOT disclose model or host absolute paths in failure outcomes. FileWrite MUST perform its final parent traversal and target open relative to a bound project-root directory descriptor, MUST NOT follow symlinks in any traversed component or the final target, and MUST fail closed if the bound root or traversed directory is replaced before the write completes.

#### Scenario: Filesystem root is the allowed root
- **WHEN** a file tool or restricted audit hook evaluates a target below `allowed_root="/"`
- **THEN** the target is treated as contained instead of being rejected by a doubled-separator prefix check

#### Scenario: A file tool receives an invalid path
- **WHEN** FileRead, FileWrite or FileList receives a syntactically invalid path such as one containing NUL
- **THEN** the tool returns its structured fixed failure outcome and does not propagate `ValueError`

#### Scenario: FileRead or FileList fails on a host path
- **WHEN** FileRead or FileList rejects an out-of-root target or receives a filesystem error whose text contains an absolute path
- **THEN** it returns the fixed detail `FileRead failed` or `FileList failed` without the model path, canonical root or exception text

#### Scenario: Non-trusted FileRead records a sanitized audit path
- **WHEN** restricted or container FileRead has a confirmer and receives an absolute in-root model path containing a known secret or non-canonical components
- **THEN** after successful path validation it preserves the normal FileRead result, does not call the confirmer or console, and emits one Python logger INFO audit containing only the known-secret-masked canonical project-relative path, without the raw model path, absolute root or secret

#### Scenario: Rejected FileRead path is not audited
- **WHEN** non-trusted FileRead receives a syntactically invalid or out-of-root path
- **THEN** it returns the fixed `FileRead failed` result and emits no path-bearing audit record, so the raw input, canonical root and known secret are not logged

#### Scenario: FileWrite target becomes a symlink after validation
- **WHEN** a FileWrite target or one of its parent components is replaced with a symlink after canonical validation but before the final descriptor-relative open
- **THEN** ForgeAgent returns the fixed `FileWrite failed` result and leaves every outside target unchanged

#### Scenario: FileWrite project-root binding changes during the write
- **WHEN** the pathname of the canonical project root is replaced after ForgeAgent opens its root directory descriptor
- **THEN** ForgeAgent fails the operation instead of reporting a successful write through a stale or attacker-controlled pathname

```

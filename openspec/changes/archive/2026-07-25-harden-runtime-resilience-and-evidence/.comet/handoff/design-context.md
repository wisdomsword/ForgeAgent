# Comet Design Handoff

- Change: harden-runtime-resilience-and-evidence
- Phase: design
- Mode: compact
- Context hash: 364374393c77703d015175039f6c5d37285c1be023fb2d997d824083cd3fc4f0

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/harden-runtime-resilience-and-evidence/proposal.md

- Source: openspec/changes/harden-runtime-resilience-and-evidence/proposal.md
- Lines: 1-30
- SHA256: a6f744a98940c62ae09b0df6f18509e7c33e3f205b8a41b26708d94a4b8ca024

```md
## Why

P0/P1 收尾后，剩余高优先级债务集中在运行时韧性与验收证据：协作 Evaluator 无法独立执行受控检查，MCP hung-call 仍由永久 skip 代替可执行回归，搜索引擎页面变化缺少运行时 fallback，真实模型与容器能力矩阵也尚未形成最新证据。与此同时，P3 中若干候选增强仍缺少真实需求，不应为了“清单完成”扩大轻量 Agent 的产品面。

## What Changes

- 为协作 Evaluator 增加专用 `RunCheck` 能力：模型只能选择宿主注册的检查 ID，不能提供命令、路径或环境；检查在临时工作副本中以无 shell、固定超时、最小环境和有界输出执行。
- 明确取消与 hard-stuck 的可承诺边界：已有 provider、executor、MCP 超时继续承担在途调用的硬边界；取消阻止后续 round/iteration/role，不能安全终止的宿主线程只允许有界脱离并报告降级，不宣称 Python 线程强杀。
- 把 MCP hung-call 的永久 skip 占位改为快速、确定性、可运行的超时回归。
- 让 `/search` 在首选引擎不可用或解析不到结果时按固定顺序尝试另一个已配置引擎，同时保持 SSRF、代理禁用和错误最小披露。
- 运行并记录可用环境中的真实模型、Evaluator、single/Triad、Docker/container 与 MCP 证据；环境不满足时记录明确阻塞，不伪造通过。
- 对 P3 候选逐项收敛：确认 native tool-call 流式聚合已实现；持久 REPL 历史、语义摘要、音视频输入、响应侧多模态继续延期，并记录可观测触发条件。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`: Evaluator 可使用宿主冻结、隔离执行的检查 ID 获取独立测试证据，且不获得普通 Exec 或任意命令能力。
- `mcp-resilience`: MCP 工具调用超时必须有快速、可重复执行的 hung-call 回归，并保持超时后的 manager 可关闭、后续状态可判定。
- `network-boundary-safety`: 搜索消费者在首选搜索引擎不可用或页面解析失效时使用固定、受限的备用引擎，而不放宽网络安全边界。

## Impact

- 主要影响 `src/forgeagent/collaboration.py`、协作装配入口、`src/forgeagent/mcp_manager.py` 的测试、`src/forgeagent/web_search.py` 及对应测试和文档。
- 不新增第三方依赖、数据库、daemon、公共协作 resume API、任意命令执行 API 或新的 sandbox 档位。
- 默认未注册检查时，Evaluator 工具集合与现有行为保持不变；现有 single/Loop/HTTP 请求 schema 不因本 change 扩大。

```

## openspec/changes/harden-runtime-resilience-and-evidence/design.md

- Source: openspec/changes/harden-runtime-resilience-and-evidence/design.md
- Lines: 1-47
- SHA256: b9c9f3c15c29472c03564446cd1a1a23dea6e868ed5a71bf1f3f1e30d173bd44

```md
## Context

现有协作 Evaluator 通过独立 Task、restricted tier 和最小 registry 与 Generator 隔离，但只能读取文件和提交 verdict，无法独立执行测试。普通 `Exec` 接受模型生成 Python，直接开放会扩大 Evaluator 的写入、进程和代码执行面。MCP manager 已有 call timeout、generation ownership 和有界 close，但唯一 hung-call 测试仍是永久 skip。`/search` 已有 Bing/DuckDuckGo 两个解析器，却只使用单一配置引擎。取消则横跨同步 provider、工具、MCP、Loop 和 Collaboration；Python 不提供安全线程强杀，必须以实际可终止句柄和已有 deadline 为边界。

## Goals / Non-Goals

**Goals:**

- 让 Evaluator 可获取独立、可复现的检查证据，同时不获得任意命令或普通 Exec。
- 把 MCP hung-call 变成 CI 可执行回归，并验证 timeout 后的关闭/世代安全。
- 为搜索页面/站点失效增加一个固定、有界且不放宽 SSRF 的 fallback。
- 用真实环境补齐能执行的 provider、Evaluator、single/Triad、container 与 MCP 证据。
- 对 P3 候选给出完成或继续延期的可验证裁决。

**Non-Goals:**

- 不尝试强杀 Python 线程，不承诺中断第三方 SDK 内部无法取消的同步调用。
- 不开放任意 shell、任意 argv、用户提交检查定义或 Evaluator 普通 Exec。
- 不实现 Agent SDK、workflow engine、并行角色、内置 scheduler、Podman backend 或新 sandbox 档。
- 不实现持久 REPL 历史、语义摘要、音视频输入或响应侧多模态。

## Decisions

1. `RunCheck` 由宿主注入 `CheckDefinition(id, argv, timeout_seconds, env)`；工具参数只有 `check_id`。argv 和 env 均由可信宿主冻结，默认空映射时不注册工具，保持兼容。
2. 检查前把允许根目录复制到私有临时目录，排除 `.git`、`.forgeagent`、缓存、构建产物和 socket/设备等特殊文件；子进程 `shell=False`、新 session、最小环境、固定 cwd，并在超时或取消时终止进程组。临时副本允许测试写缓存但不修改真实项目。
3. stdout/stderr 分别有字节上限，返回稳定 status/exit code/duration；输出经现有 secret masking 并把临时绝对路径替换为相对占位。
4. CLI/HTTP 不接受客户端定义检查。检查可引用宿主已有解释器或可执行文件，cwd 始终为临时副本，且不得在副本内创建环境或下载依赖。ForgeAgent 自身的证据运行可在测试/装配层显式注入检查定义；若以后需要用户配置，另立 change 设计信任边界。
5. 取消只承诺安全边界停止。`RunCheck` 有真实子进程句柄，因此支持取消即终止；provider/MCP 继续依靠自身 timeout，返回后不得启动下一角色/round。
6. MCP hung-call 测试复用本地 async session test double，在 manager 的 loop 上制造永不完成调用，并使用短 `call_timeout` 证明固定 timeout 和 close deadline，不启动真实 server。
7. 搜索按 `[preferred, other_builtin]` 固定顺序最多两次。首选失败或零结果均 fallback；最终有结果即成功，否则错误优先级为 blocked 高于 unavailable，高于零结果。
8. 真实模型和 Docker 是验证步骤：读取现有配置但不输出 credential；产生费用的调用限制为既有 20 项中声明的 5 项 real-model golden 和一个小型 single/Triad/Evaluator 对比数据集。
9. P3 裁决写入状态文档：native tool-call 流式聚合已有回归，标记完成；其余增强仅在出现明确用户场景、可衡量失败或 provider 合同后重开 change。

## Risks / Trade-offs

- 临时副本会增加 I/O，且不能复现依赖项目根外部未声明文件的测试；通过小型排除表和明确检查失败处理，不构建通用 VCS snapshot 系统。
- 检查进程的子进程树在 Windows 与 POSIX 终止方式不同；优先实现并测试 POSIX process group，Windows 使用 `CREATE_NEW_PROCESS_GROUP`/terminate 的最小兼容路径。
- 搜索零结果 fallback 会增加一次网络请求；最多两个固定 host，且仅 `/search` 显式调用触发。
- 真实模型结果受模型版本和供应商状态影响；报告只陈述当次证据，不把单次对比写成永久质量保证。

## Migration Plan

无数据或配置迁移。默认无检查定义时行为不变；搜索只增加失败路径上的备用请求。回滚可直接移除 `RunCheck` 注册、恢复单引擎搜索和测试变更，不影响持久 schema。

## Open Questions

无阻塞项。Podman/Linux 原生容器矩阵若当前主机不具备环境，只记录为外部环境缺口，不在本 change 添加未验证 backend。

```

## openspec/changes/harden-runtime-resilience-and-evidence/tasks.md

- Source: openspec/changes/harden-runtime-resilience-and-evidence/tasks.md
- Lines: 1-25
- SHA256: d03344f9c651fe4a70d3726ab68b7e43d0617b6f0b67f3dfeab77d997a945349

```md
## 1. Evaluator 隔离检查与取消边界

- [ ] 1.1 以失败测试定义 `CheckDefinition`、`RunCheck` 仅接收检查 ID、默认不注册和未知 ID 不启动子进程
- [ ] 1.2 以失败测试定义临时副本排除规则、无 shell/最小环境/固定 cwd、输出脱敏与上限、退出码和清理
- [ ] 1.3 以失败测试定义 timeout/cancel 终止检查进程组，并验证取消后不启动下一协作角色或 rejection attempt
- [ ] 1.4 实现最小 `RunCheck` 工具、registry 接线和宿主注入接口，不扩大 CLI/HTTP 请求 schema 或普通 Evaluator 权限

## 2. MCP 与搜索可靠性

- [ ] 2.1 将永久 skip 的 MCP hung-call 占位改为短 deadline 本地回归，验证固定 timeout、迟到结果隔离和有界 close
- [ ] 2.2 以失败测试定义搜索首选引擎网络失败、非成功状态和零结果时的单次固定 fallback，以及 blocked/unavailable/zero 的最终优先级
- [ ] 2.3 实现双引擎有界 fallback，确保每次请求继续独立经过既有 SSRF、redirect、scheme 和 proxy 策略

## 3. P2/P3 证据与裁决

- [ ] 3.1 在可用环境运行 container 真实集成矩阵；若 Docker/镜像或 Linux/Podman 环境缺失，记录精确阻塞而不伪造通过
- [ ] 3.2 使用现有凭证运行既有 5 项 real-model golden、credentialed Evaluator 和小型 single/Triad 对比，记录模型、费用边界、原始通过率与失败原因
- [ ] 3.3 复核 native tool-call 流式聚合已有实现与回归；为持久 REPL 历史、语义摘要、音视频和响应侧多模态记录明确重启触发条件
- [ ] 3.4 更新 README、ACTION_PLAN、威胁模型、协作文档与里程碑续接状态，只陈述已验证保证和本机证据

## 4. 验证与收尾

- [ ] 4.1 运行相关专项、完整 pytest、Ruff format/check、离线 golden、wheel/sdist、OpenSpec strict 和 diff check
- [ ] 4.2 完成两轮需求/设计/实现自审与独立代码审查，修复所有 Critical/High/Important 问题
- [ ] 4.3 生成验证报告和里程碑收尾记录，归档 change，并按验证结果处理工作分支

```

## openspec/changes/harden-runtime-resilience-and-evidence/specs/mcp-resilience/spec.md

- Source: openspec/changes/harden-runtime-resilience-and-evidence/specs/mcp-resilience/spec.md
- Lines: 1-12
- SHA256: ff50bbd7f9401bb6b5d147e71430570a296105a624589bbbf6c182b43e8e43a9

```md
## ADDED Requirements

### Requirement: MCP hung-call 超时具有可执行回归
MCP manager MUST 对已建立 session 上永不返回的工具调用应用共享调用 deadline，并在 deadline 到达后返回固定、脱敏的 timeout 失败。验证该行为的自动化测试 MUST 使用确定性本地 test double、在短时间内完成且不得永久 skip。超时不得使 `close()` 无界阻塞，也不得把迟到结果发布到已失效 generation。

#### Scenario: 永不返回的 MCP 工具调用超时
- **WHEN** 一个本地 MCP test double 接受工具调用但在配置的 call timeout 内永不完成
- **THEN** `call_tool` 在 deadline 后返回固定 timeout 结果，测试在有界时间内通过且不依赖公网或用户 MCP 配置

#### Scenario: hung-call 后关闭 manager
- **WHEN** manager 在一次工具调用超时后关闭
- **THEN** `close()` 在既有 shutdown deadline 内返回，迟到 holder 或调用结果不能恢复旧 generation

```

## openspec/changes/harden-runtime-resilience-and-evidence/specs/network-boundary-safety/spec.md

- Source: openspec/changes/harden-runtime-resilience-and-evidence/specs/network-boundary-safety/spec.md
- Lines: 1-20
- SHA256: 1ce61eb5b6da77de58aaf3974515f0720ca394a34f84f86e05b2a5d4b0c9afdf

```md
## ADDED Requirements

### Requirement: 搜索消费者使用固定受限的引擎 fallback
`/search` MUST 把配置引擎视为首选而非单点依赖。当首选引擎网络失败、返回非成功状态、或成功页面解析为零条结果时，运行时 MUST 最多再尝试一次另一个内置引擎。每次请求 MUST 独立经过既有无代理、SSRF、redirect 和 scheme 校验；不得根据页面内容或用户输入构造第三方 host。若所有尝试失败，公开错误仍 MUST 使用既有稳定最小披露状态。

#### Scenario: 首选引擎不可用时 fallback
- **WHEN** 首选引擎请求因网络错误或非成功状态失败
- **THEN** 运行时尝试另一个固定内置引擎，并在备用引擎成功时返回其结果

#### Scenario: 首选页面解析失效时 fallback
- **WHEN** 首选引擎返回成功页面但解析器得到零条结果
- **THEN** 运行时尝试另一个固定内置引擎，以避免单一 HTML 结构变化导致永久空结果

#### Scenario: 每个 fallback hop 独立受网络策略约束
- **WHEN** 首选或备用引擎的任一有效目标、redirect 或解析前请求违反网络策略
- **THEN** 该请求被既有 guard 拒绝，fallback 不绕过 scheme、proxy、redirect 或 SSRF 限制

#### Scenario: 所有引擎失败
- **WHEN** 两个固定引擎均不可用或均解析不到结果
- **THEN** `/search` 返回既有 unavailable 或零结果公开语义，不披露内部 URL、异常、credential 或代理信息

```

## openspec/changes/harden-runtime-resilience-and-evidence/specs/runtime-collaboration/spec.md

- Source: openspec/changes/harden-runtime-resilience-and-evidence/specs/runtime-collaboration/spec.md
- Lines: 1-39
- SHA256: d27e2f38b4a9dc7c40f1c24f59364b4f0956cb216e14c7d0fc88e6db10a129fe

```md
## ADDED Requirements

### Requirement: Evaluator 只能执行宿主冻结的隔离检查
协作运行时 MUST 允许宿主为 Evaluator 注册零个或多个稳定检查 ID。Evaluator 只能提交检查 ID，MUST NOT 提交或覆盖 argv、shell 文本、工作目录、环境变量、超时或输出上限。检查 MUST 在项目临时工作副本内以无 shell 子进程执行，使用宿主冻结的参数、最小环境、固定超时和有界输出；检查结果 MUST 作为不含绝对路径和已知 secret 的结构化证据返回。未注册检查时 MUST 保持既有 Evaluator 工具集合与行为。

#### Scenario: Evaluator 运行已注册检查
- **WHEN** Evaluator 调用 `RunCheck` 并选择宿主已注册的检查 ID
- **THEN** 运行时在临时工作副本中执行该检查的冻结 argv，并返回稳定状态、退出码、耗时和有界脱敏输出

#### Scenario: Evaluator 请求未知检查
- **WHEN** Evaluator 提交不存在或未向本次协作注册的检查 ID
- **THEN** 运行时返回结构化失败且不启动任何子进程

#### Scenario: 检查超时
- **WHEN** 已注册检查超过其冻结超时
- **THEN** 运行时终止对应子进程组、返回稳定的 timeout 结果，并清理临时工作副本

#### Scenario: Evaluator 不能注入命令
- **WHEN** 模型输出尝试携带 argv、shell、路径、环境或其他未定义字段
- **THEN** 协议校验拒绝该调用，普通 `Exec` 仍不在 Evaluator registry 中

#### Scenario: 未配置检查保持兼容
- **WHEN** 宿主没有为本次协作注册任何检查
- **THEN** Evaluator registry 仍只包含既有只读文件与提交验收工具，不广告 `RunCheck`

### Requirement: 协作取消遵循可实现的有界停止语义
协作运行时 MUST 在每个安全边界检查取消并阻止启动新的 Planner、Generator、Evaluator 或 rejection attempt。已经进入 provider、工具或宿主检查的操作 MUST 由各自冻结超时或子进程终止机制收敛；运行时 MUST NOT 声称能够异步强杀 Python 线程。取消后返回的终态报告仍按既有 HTTP 终态优先级发布。

#### Scenario: 角色开始前取消
- **WHEN** cancel signal 在下一个协作角色或 rejection attempt 启动前已设置
- **THEN** 协作以 `cancelled` 停止且不构造或调用该角色

#### Scenario: 检查执行期间取消
- **WHEN** cancel signal 在 `RunCheck` 子进程执行期间设置
- **THEN** 运行时终止检查子进程组并返回取消结果，不等待完整检查超时

#### Scenario: 不可异步中断的宿主调用
- **WHEN** cancel signal 在一个没有安全强杀句柄的宿主线程调用期间设置
- **THEN** 运行时等待该调用自身冻结超时或返回，再于下一个安全边界停止，且文档不宣称即时硬取消

```

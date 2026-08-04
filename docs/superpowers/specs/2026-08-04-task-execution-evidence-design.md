---
comet_change: expose-task-execution-evidence
role: technical-design
canonical_spec: openspec
---

# 任务执行证据技术设计

## 背景

ForgeAgent 当前把代码块和工具结果保存在内存中。`CodeBlock.path` 是不可信的 Markdown 元数据，`Step` 存储代码块时会丢弃它；内联 Exec 代码在 backend dispatch 前也只存在于内存。任务结束后，各入口无法稳定、安全地回答实际尝试了哪些工具，以及执行过的生成代码保留在哪里。

本 change 的 OpenSpec delta specs 是需求事实源。本文只定义实现结构，并关闭制品命名空间、容量、保留、HTTP、聚合和失败处理决策。

## 目标与边界

- 只记录已经进入运行时 dispatch 的工具，并保持确定性尝试顺序。
- 每次 Exec 在 trusted、restricted 或 container backend dispatch 前持久化实际选中的代码。
- CLI/REPL 只输出一次终态汇总；HTTP、Loop、Duo、Triad 增加有界证据。
- 保持既有 Task 状态、工具成功语义、sandbox 权限、HTTP 认证和完成完整性不变。
- 公开证据排除原始参数、代码、stdout/stderr、prompt、secret、任意文件内容和非本地绝对路径。

未捕获的进程级异常继续采用既有异常处理。本 change 所称 `failed` 是现有结构化 Task、Loop、Collaboration 终态，不把基础设施异常转换为成功返回值。

## 方案比较

### 方案一：终态扫描 rounds

这是 Task 层最小改动，但会把证据语义耦合到 rounds 保留形式，容易混淆“已解析”和“已尝试”，也无法独立保证 Loop 或 Collaboration 恢复后的证据一致性。

### 方案二：Task 级 recorder 与程序 store

采用该方案。工具 dispatch 边界记录证据，Exec backend 边界持久化程序，聚合 runner 把有界安全投影写入 durable state。它新增一个共享模块，但每层职责明确，并能覆盖取消和恢复。

### 方案三：复用 audit log

审计日志已经观察操作，但它可独立降级，保留策略不同，也不是用户结果 API。用它生成终态结果会同时削弱审计和用户结果契约。

## 数据模型

新增 `execution_evidence.py`，放置不可变模型和纯投影函数：

- `ProgramArtifact`：canonical relative reference，以及声明为 Pydantic `exclude=True` 的私有本地路径。通用 `TaskOutcome.model_dump()` 不会输出本地路径，本地 renderer 仍可读取内存字段。
- `ToolExecutionRecord`：sequence、tool、稳定 status（`succeeded`、`failed` 或 `artifact_persistence_failed`）、可选 block、可选 artifact，以及可选聚合来源（iteration、role、attempt）。
- `ExecutionEvidence`：有序 records、`truncated` 和 `omitted_count`。
- `ExecutionEvidenceRecorder`：Task 内 append-only recorder，最多保留 128 条。后续尝试只增加 `omitted_count`，不改变已保留前缀。

`TaskOutcome` 增加默认空的 `execution_evidence` 字段。`ToolOutcome` 增加可选程序制品和稳定证据状态覆盖；现有构造器保持兼容。成功结果映射为 `succeeded`，普通失败映射为 `failed`，程序 store 的 fail-closed 失败映射为 `artifact_persistence_failed`。

公开投影保留前 32 条记录，对 tool、block、reference 使用固定字符上限，移除本地路径，掩码已知 secret，转义不安全显示字符，并报告合并后的 omitted 数量。空证据使用显式空 envelope，不省略也不伪造工具。

## 程序制品 Store

每个 Task 延迟创建一个宿主 UUID 命名空间：

```text
<immutable-project-root>/.forgeagent/execution-artifacts/<execution-id>/programs/
```

公开引用从 `execution-artifacts/` 开始，并且只能包含 canonical relative POSIX segments。文件名使用 Task 内 Exec sequence 和宿主清理后的 block label；Python 扩展名为 `.py`。模型提供的 `CodeBlock.path` 永远不参与路径选择。

Store 使用 `lstat` 遍历或创建各级目录，拒绝 symlink 和非目录，持有 programs 目录 descriptor，并在发布前后校验 pathname 与 descriptor 绑定。写入流程使用 `O_CREAT|O_EXCL|O_NOFOLLOW` 创建权限为 0600 的唯一临时普通文件，写入后 flush 和 fsync，再通过 descriptor-relative `os.replace` 原子发布，fsync 目录并校验最终普通文件。新建私有目录权限为 0700。

backend dispatch 前执行固定上限检查：

- 每个 Task 最多 100 个程序文件；
- 单文件 UTF-8 最大 1 MiB；
- 每个 Task 的 UTF-8 总量最大 8 MiB。

编码、目录、绑定、临时写入、发布、权限或容量失败都返回稳定 `artifact_persistence_failed` ToolOutcome，不包含 artifact reference。临时文件执行 best-effort 清理；发生上述失败后绝不调用 backend。

## 运行时数据流

1. `Task` 解析 immutable project root，创建一个 recorder 和一个延迟 program store，并传给 `Step`。
2. `Step` 继续按现有逻辑存储解析出的代码块。只有 `_dispatch` 调用注册工具时才形成证据；完成工具之后被跳过的调用不记录。
3. `ExecTool` 解析内联或命名代码，运行现有静态分析，让 program store 持久化实际代码，成功后才 dispatch backend。
4. `_dispatch` 把返回的 ToolOutcome 追加到 recorder。取消会阻止后续调用，并保留此前记录。
5. `Task.run` 为每个现有结构化终态把 recorder snapshot 放入 `TaskOutcome`。

该顺序不改变 Edit 和 block versioning。编辑后的代码再次执行时会产生新的不可变程序文件，因此每个 Exec attempt 都能指向实际运行版本。

## 入口投影

`render_outcome` 在终态状态之后增加一个 `execution evidence` 区域，列出所有保留工具及稳定状态，为每个程序显示本地绝对路径；prose 或其他空结果明确显示没有工具或程序执行。现有有界 stdout 和失败详情保持独立，不复制进证据模型。

REPL 复用同一个 `run_once` renderer。Loop 和 Collaboration renderer 接收已知 project root，只解析 `.forgeagent` 下经过验证的 `execution-artifacts/...` 引用；不安全引用显示为 unavailable，不执行路径拼接。

`TaskRecord.public_view` 只为 terminal record 增加 `execution_evidence`。普通 Task 使用 public projector，Loop/Collaboration 使用报告中的安全证据。running record 不生成终态证据；终态空结果包含显式空 envelope。

HTTP 只返回相对引用，不新增 route 或下载端点。测试一方面证明引用在内部映射到配置 project root 下的持久化文件，另一方面证明公开 JSON 不含 host root、代码、参数、prompt、secret 或原始异常。

## Durable 聚合

`LoopCheckpoint` 和 `CollaborationState` 增加默认空的证据字段，既有 v1 文件无需重写即可加载。durable state 只存安全相对记录，绝不存 Task 本地绝对路径。

Collaboration 在保存角色统计之前追加角色 Task snapshot，并标注 role 和 attempt；`CollaborationReport` 投影该有界状态。Loop 为普通 Task 记录 iteration；嵌套 collaboration 保留 role/attempt，只为新观察到的记录增加当前 iteration，并用来源加 Task sequence 去重累计报告。所有聚合公开前缀最多 32 条，并携带 omitted 数量。

证据与 child outcome 计数在同一次原子状态变更中保存。恢复时先加载既有前缀再执行新工作，不为被阻止的工作伪造证据，也不重复累计角色记录。

## 保留与兼容性

程序文件在 Task.close、terminal HTTP record 过期、Loop close 和 Collaboration close 后仍持久存在。这样本地显示路径保持有效，也避免一个 consumer 删除另一个 consumer 引用的证据。项目或宿主运维者负责清理 `.forgeagent/execution-artifacts/`；自动 GC、全局 quota、远程存储和下载授权是后续独立能力。

单 Task 上限只约束一个 execution namespace，不宣称限制全部历史磁盘占用。HTTP reference 在 terminal record 被保留期间是稳定结果元数据；由于没有下载端点，它不是远程解引用承诺。

所有结果字段都是带空默认值的加法式字段。既有 status enums、report schema strings、checkpoint/state 文件，以及忽略 execution evidence 的调用方保持兼容。

## 错误处理

- 缺失命名 block 保持普通失败 Exec，不产生 artifact。
- 程序持久化失败使用稳定、无路径、fail-closed 结果。
- backend 失败保留已经成功持久化的 artifact，并报告 `failed`。
- 证据投影拒绝或替换不安全 label/reference，但不改变底层工具结果。
- 既有 state-size 校验仍是最终边界；固定证据前缀需保持在现有 256 KiB checkpoint/state 上限内。

## 测试策略

按垂直切片执行 TDD：

1. Program store：精确字节、权限、命名、symlink/rebinding、临时清理、数量/单文件/总量，以及 backend 未 dispatch。
2. Exec：trusted/restricted/container 的命名和内联代码、编辑版本、持久化失败、模型 path metadata 无权限。
3. Step/Task：尝试顺序、成功/失败、parsed-but-skipped、direct prose 空证据、结构化失败、取消保留。
4. CLI/REPL：一次终态汇总、本地路径、secret/control-safe label、显式空结果、无逐轮重复。
5. HTTP：terminal-only 证据、安全相对引用、内部文件关联、空结果、上限，以及无绝对路径/代码/参数/prompt/secret/异常泄露。
6. Loop/Collaboration：来源、全局截断、取消、checkpoint/state 恢复、嵌套去重、旧状态空默认。
7. 最后运行受影响测试、Ruff、OpenSpec strict 和全量 pytest。

## 实现顺序

先实现共享 evidence/store 模块及测试，再依次接入 ToolContext/Exec、Step/Task、CLI/REPL、HTTP、Loop、Collaboration。每层变绿后再推进外层。不新增依赖或配置面。

## Context

当前执行链路没有可持久引用的程序制品：`CodeBlock.path` 是模型提供的 markdown 元数据，`Step` 把代码写入 `StoredBlock` 时会丢弃该字段；`StoredBlock` 和 `ToolOutcome` 也没有 artifact 字段。命名块、内联 Exec、restricted worker 和 container worker 都以内存或 stdin 传递代码，终态结果无法证明具体执行了哪个程序。CLI 虽会渲染轮次工具结果，HTTP、Loop 和 collaboration 只保留既有有界公开投影。

该 change 是 M48 唯一需要完整设计的新能力。本 open 文档只固定跨模块契约和安全边界；具体数据模型、容量与生命周期在后续 full design 阶段通过 brainstorming 决定。交付顺序固定为先完成并分别 verify/archive 三个 port change，再基于已集成三项行为的 `main` 开始本 change 的 build；不得与 `port-task-filesystem-authority` 并行修改 `tools.py`、ToolContext 或 Exec 接入点。

## Goals / Non-Goals

**Goals:**

- 每个 Task 在终态提供实际尝试的工具、稳定状态和关联程序制品证据。
- 所有准备交给 executor 的生成代码在执行前写入任务级制品目录，包括命名块与内联 Exec。
- CLI、HTTP、Loop、Duo、Triad 都在终态一次性投影有界证据；失败、停止和取消保留已发生尝试。
- CLI 显示本地程序路径，HTTP 只显示安全相对制品引用。

**Non-Goals:**

- 不逐轮重复输出汇总，不暴露原始工具参数、凭据、prompt、文件内容或 HTTP 宿主绝对路径。
- 不把模型提供的 `CodeBlock.path` 直接信任为宿主写入路径。
- 不在本 change 中建立通用制品下载服务、远程对象存储或任意工具输出归档系统。
- 不改变工具成功/失败语义、sandbox tier 或任务完成完整性规则。

## Decisions

1. 在 Task 拥有的执行证据收集器中追加记录，而不是在终态重新扫描 rounds。记录点位于工具实际尝试边界，可覆盖成功、失败、停止和取消，并由 `TaskOutcome`、LoopReport 与 CollaborationReport 做加法式投影。
2. Exec 在调用任何 backend 前统一物化程序制品。命名块和内联代码都走同一写入路径；制品名由宿主生成安全任务内名称和语言扩展，不采用模型给出的绝对或相对 `CodeBlock.path` 作为落盘目标。
3. 程序制品必须先原子持久化再执行。若制品写入失败，该 Exec 返回稳定失败且不得把未留证据的代码交给 trusted/restricted/container backend。
4. 内部证据同时携带宿主本地路径和任务内相对引用。CLI 只在本地主机上下文渲染本地路径；HTTP、Loop 的 HTTP 投影和其他公共 JSON 只渲染安全相对引用。
5. 公开记录只包含有界工具名、稳定状态、可选安全 block 名和可选制品引用。原始 args、代码正文、stdout/stderr、绝对宿主路径和异常正文继续由现有投影边界排除。
6. Single Task 是证据所有权基本单元。Loop 按迭代聚合，Duo/Triad 按角色/attempt 聚合并应用全局上限；终态只渲染一次，普通 prose 明确投影空证据集合。
7. 程序制品固定写入 immutable project root 下的 `.forgeagent/execution-artifacts/<execution-id>/programs/`；`execution-id` 由宿主生成，不复用外部 task ID。每 Task 最多 100 个程序、单文件最多 1 MiB、合计最多 8 MiB；内部工具尝试保留 128 条，公开投影保留 32 条并报告 omitted 数量。
8. HTTP 只返回 `execution-artifacts/...` canonical relative POSIX 引用，不新增下载端点。测试必须从内部项目根验证引用对应已持久化文件，同时证明公开 JSON 不含绝对路径。引用仅在 terminal record 可查询期间作为结果元数据稳定，不承诺 HTTP 解引用能力。
9. M48 不实现自动 GC。Task、HTTP record、Loop 与 collaboration 关闭或过期都不删除已公开程序路径；项目/宿主运维者负责清理 `.forgeagent/execution-artifacts/`。目录权限为 0700、文件权限为 0600，单 Task 容量限制控制局部增长。

## Risks / Trade-offs

- [程序制品包含模型生成的敏感字面量] -> 终态和 HTTP 不展示代码内容；后续设计需明确本地文件权限、保留和清理策略。
- [证据写入使原本可执行的代码失败] -> fail closed，保证“执行过的程序一定有路径”契约，不产生不可审计执行。
- [Loop/协作聚合无限增长] -> 后续设计定义稳定排序、条目/字符/字节上限和截断标记。
- [与 HTTP record retention 生命周期不一致] -> 后续设计明确引用有效期和清理所有权；在此之前不承诺下载能力。
- [新增结果字段影响调用方] -> 只做带默认空集合的加法式字段，保留既有字段与终态枚举。
- [跨任务持久制品持续占用磁盘] -> 本 change 固定单 Task 数量/字节上限并明确项目运维清理所有权；自动 GC 作为独立后续能力，不与结果契约耦合。

## Migration Plan

open/design 的初始语义基准来自 `main` M47 提交 `cc6472566cf13d5449b151f3047dcb8455db0d55`，不得使用旧分支 HEAD `3245a448` 判定改动归属。三个 port change 均已 verify/archive 并集成；本 change 的实现基线固定为集成提交 `cf51c632a71fa810f81397401d215c8990f1c4ee`，后续 build/verify 只比较该提交之后的执行证据差异。无旧数据迁移。实现按“Task 内部证据与制品 -> Exec 接入 -> Single CLI -> HTTP -> Loop/Collaboration”逐层推进，每层先建立失败测试。回滚可移除加法式字段和新制品写入，不改变现有任务状态数据。

## Resolved Questions

- 制品位于 immutable project root 的 `.forgeagent/execution-artifacts/<execution-id>/programs/`，角色与迭代只作为证据来源字段，不参与不受信任的路径命名。
- 固定上限为每 Task 100 个程序、单文件 1 MiB、总量 8 MiB；任何制品持久化或容量失败都返回稳定 `artifact_persistence_failed`，且不 dispatch backend。
- 制品持久保留，项目/宿主运维者负责清理；HTTP 引用仅在 terminal record 可查询期间作为元数据稳定，Task/record/runner close 不删除文件。
- HTTP 只提供安全相对引用，不增加下载端点；验收通过内部项目根解析确认引用与文件关联，并单独验证公开投影不泄露绝对路径。

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

---
comet_change: m28-v0-1-release-candidate
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-29-m28-v0-1-release-candidate
status: final
---

# M28 v0.1 Release Candidate 技术设计

## 1. 目标与约束

M28 将 ForgeAgent `0.1.0` 从“源码仓库内测试通过”推进到“候选分发包的关键入口可重复验收”。权威需求仍是 OpenSpec delta spec；本文只细化实现边界、数据流和验证方法。

设计必须同时满足：从真实 wheel 安装；Python 3.11 最低支持版本；不依赖仓库 `src/`；不使用 provider credential 或网络模型；CLI/HTTP/Single/Duo/Triad 都经过安装后代码；Linux Docker CI 不接受 skip；报告有界且不泄密。M28 不上传包、不打 tag、不 push、不新增产品能力或依赖。

## 2. 方案比较与选择

### 方案 A：产品新增 `forgeagent rc-smoke`

优点是入口直观，缺点是把发布工程永久加入 public CLI，还需要决定长期兼容、帮助文档和安装后如何创建测试替身。RC 门禁不是用户任务能力，因此拒绝。

### 方案 B：为 CLI、HTTP、协作分别创建脚本

每个脚本较短，但会重复 venv、environment scrub、wheel provenance 和 JSON 证据逻辑；CI 还需协调多个失败口径。重复面大于分离收益，因此拒绝。

### 方案 C：单一父/子模式 harness（采用）

一个仓库级脚本负责环境准备与全部 smoke。父模式只处理 wheel/venv/subprocess；子模式只处理安装后运行时验收。边界清楚、无新依赖、测试与 CI 复用同一入口，符合 Ponytail 的最小实现约束。

## 3. 组件与数据流

### 3.1 父模式：候选包与隔离环境

公开参数保持最小：

- `--wheel PATH`：唯一候选 wheel。
- `--output PATH`：最终 JSON 证据路径。
- `--python PATH`：可选目标解释器；默认当前解释器，Linux RC gate 显式使用 Python 3.11。

内部子模式参数不作为用户文档入口。父模式按以下顺序执行：

1. 将 wheel 解析为普通文件，读取 `.dist-info/METADATA`，要求 Name 为 `forgeagent`、Version 为 `0.1.0`，计算 SHA-256。
2. 在 `TemporaryDirectory` 中用目标解释器的 `venv` 模块创建全新环境。
3. 通过新环境的 `python -m pip install <wheel>` 安装候选及依赖；安装命令不包含 editable/source path。
4. 清除 `PYTHONHOME`、`PYTHONPATH` 和 provider credential，设置临时 `HOME`，从不在仓库根下的 probe cwd 以 `python -I` 启动同一脚本的子模式。
5. 子模式成功后校验报告 schema 和六个必需检查；任何不完整状态都使父模式非零退出。

父模式在安装或子进程失败时仍原子写出失败报告。报告只含固定错误类别，不复制 pip、CLI、HTTP 或模型输出。详细命令失败仅向 stderr 输出固定、无路径的检查名。

### 3.2 子模式：安装来源证明

子模式首先读取 `importlib.metadata.version("forgeagent")`，要求 `0.1.0`；再解析 `forgeagent.__file__`、`sys.prefix` 和 console script，要求模块与入口都位于当前 venv，且入口是普通文件。它通过 `importlib.resources` 读取内置模型 YAML 和必需 prompt，防止只有顶层模块可导入而 package data 遗漏。

脚本文件本身可以从仓库挂载路径执行，但 `-I` 会忽略 `PYTHON*` 覆盖，脚本目录只有 `scripts/`，并不包含 `src/forgeagent`；来源断言进一步阻止错误环境蒙混过关。

### 3.3 CLI smoke

用 `subprocess.run(..., shell=False)` 直接执行 venv 中的 console script：

1. `forgeagent --help`：状态为 0，输出包含程序说明及 `run`、`serve`。
2. `forgeagent models`：状态为 0，输出包含包内默认模型标识。

命令继承已清洗环境和临时 HOME，不执行 `run`/`smoke`，因此不会创建 provider client 或发真实请求。验证只匹配稳定标识，不锁定 Rich 布局全文。

### 3.4 HTTP smoke

使用公开 `HttpServiceConfig`、`TaskService` 和 `create_http_server`，绑定 `127.0.0.1:0`。本地任务替身只实现 `run()`/`close()`：`run()` 在 event 上有界等待，收到 HTTP cancel 后返回稳定 cancelled outcome。server 在单独 daemon thread 执行 `serve_forever()`。

用标准库 `urllib.request` 发真实请求：

1. 无 token 提交，要求 `401` 且 registry 为空。
2. 带 bearer token `POST /tasks`，要求 `202` 和 32 字符 task id。
3. `GET /tasks/<id>`，要求公开状态是 queued/running。
4. 取消端点请求，要求稳定 cancelled 投影；再次查询保持终态。

`finally` 中依次 `server.shutdown()`、`server.server_close()`、`TaskService.shutdown()` 并 join thread。端口分配、线程退出或状态超时均为失败，不 skip。

### 3.5 Single/Duo/Triad smoke

所有模型回复由包内 `MockClient` 的固定消息序列产生。固定序列使用真实文本协议和工具调用 parser，不直接修改状态文件。

- Single：真实 `Task` 接收一个完成回复，要求 `TaskOutcome.status == "completed"`，且没有 collaboration report。
- Duo：`CollaborationRunner.create()` 生成 store/state。Generator 调用零载荷 `SubmitCandidate`；Evaluator 调用 `SubmitEvaluation` 提交全部冻结验收项 pass。要求 report mode/status 为 `duo/completed`，attempt 和 pass 计数符合固定脚本。
- Triad：Planner 先调用 `SubmitPlan` 提交一项可观察验收，固定 confirmer 返回批准；Generator/Evaluator 复用结构化完成链。要求 `triad/completed`、plan digest 非空且一项通过。

每个 role 都由最小 builder 创建真实 `Task(client, tool_registry=registry, system_prompt=...)`，完成后关闭 task/client。临时 collaboration root 在退出时删除；JSON 不记录 collaboration id、目标、计划正文或模型回复。

## 4. 报告合同与错误处理

报告 schema 为 `forgeagent.release-candidate-smoke/v1`，顶层固定字段：

```json
{
  "schema": "forgeagent.release-candidate-smoke/v1",
  "version": "0.1.0",
  "python": "3.11.x",
  "wheel_sha256": "<64 lowercase hex>",
  "passed": true,
  "checks": {
    "clean-wheel": "passed",
    "cli": "passed",
    "http": "passed",
    "single": "passed",
    "duo": "passed",
    "triad": "passed"
  }
}
```

状态只允许 `passed`、`failed`、`not-run`。成功要求六项全部 `passed`；`not-run` 永远不等价于 skip-success。写入使用同目录临时文件、flush、`os.fsync()`、`os.replace()`，避免 CI 收到半份 JSON。失败报告不含 exception 字符串、stdout/stderr、环境或路径。

父子 subprocess 都设置有界 timeout。超时后由 `subprocess.run` 清理直接子进程；HTTP/Task/Collaboration 自身在 `finally` 关闭。脚本不创建后台常驻进程。

## 5. CI 集成

保留 `linux-docker-container` 的 Docker 29.2.1 DinD、`python:3.11-slim` worker image 预检、非 root pytest 和十项 JUnit 精确断言。container tests 通过后：

1. `uv build --wheel` 生成单一候选 wheel。
2. 使用已拉取的 `python:3.11-slim` 启动一次性 Linux 容器，挂载同路径项目卷、使用 uid/gid 1000 和项目内 TMPDIR，运行 RC harness。
3. 校验 `artifacts/ci/rc-smoke.json` 的 schema、`passed: true` 和六个 `passed` 状态。
4. 将 JSON 与 container JUnit 一并声明为 `when: always` artifact。

RC 容器安装 wheel 依赖需要普通包索引连通性；安装失败即 gate 失败。安装结束后的 smoke 不使用 provider 网络或 credential。CI 不从 macOS Docker 结果外推 Linux 通过。

## 6. 文档冻结

`docs/releases/0.1.0-rc.md` 是 RC 发布口径的单一入口，必须包含：

- 候选状态与安装方式；
- CLI、HTTP、Single/Duo/Triad、sandbox、Memory/Skills/Loop 等已交付范围；
- clean-wheel、Linux Docker、pytest、Golden、OpenSpec 的实际验证结果；
- 正式发布前阻塞条件；
- 平台、真实模型、sandbox、HTTP、协作五类已知限制。

README 只增加显著链接和当前 RC 状态，不复制长限制。`docs/platform-support.md` 只在真实命令完成后加入证据；如果 required CI 尚未运行，写 configured/待 CI 复验，不能复用 M24 历史 container 运行冒充 M28 wheel smoke 通过。

## 7. 测试策略

### 7.1 单元与合同测试

新测试按路径导入脚本，覆盖：wheel metadata/name/version；SHA-256；环境清洗；venv/console path；报告原子替换；失败只含固定状态；六项完整性。subprocess 构造使用 fake runner 验证 `shell=False`、`-I`、临时 HOME 和不含源码路径。

### 7.2 入口集成测试

直接调用子检查：CLI 使用真实当前 console/module 等价入口；HTTP 使用真实 loopback；Single/Duo/Triad 使用真实 runtime + MockClient。测试断言终态和计数，不快照非稳定输出或 UUID。

### 7.3 分发包与系统验证

`tests/test_packaging.py` 保留 sdist allowlist 和 prompt resource 断言，并以真实构建 wheel调用同一 harness，替代现有重复的手写 venv probe。最终运行专项 pytest、完整 pytest、Ruff check/format、Golden 20/20、OpenSpec strict、`uv build`、本机 Docker 十项，以及 Python 3.11 Linux 容器内 RC smoke。

## 8. 两轮设计自审

第一轮检查需求映射、非目标和最小性：每个 OpenSpec requirement 都有组件和验证入口；没有新增产品命令、依赖、抽象层或 provider 行为。

第二轮检查歧义、错误路径和证据真实性：明确了 Python 3.11、console script 来源、真实 loopback、三种协作结构化完成、失败报告、零 skip 以及 M24 历史证据不能替代 M28。未发现需回写 delta spec 的缺口。


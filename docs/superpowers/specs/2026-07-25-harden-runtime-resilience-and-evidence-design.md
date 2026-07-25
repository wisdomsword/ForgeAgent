---
comet_change: harden-runtime-resilience-and-evidence
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-25-harden-runtime-resilience-and-evidence
status: final
---

# 运行时韧性与证据收尾技术设计

## 1. 设计结论

本 change 用三个最小改动收敛剩余可落地债务：Evaluator 获得宿主冻结的隔离检查、MCP hung-call 获得可执行回归、`/search` 获得固定双引擎 fallback。取消语义按真实可终止句柄收敛，不承诺 Python 线程强杀。真实模型、Docker 与 P3 候选作为验证和路线裁决，不混成新的运行时框架。

## 2. Evaluator `RunCheck`

### 2.1 数据模型

在 `collaboration.py` 中新增冻结模型：

```python
class CheckDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    argv: tuple[str, ...]
    timeout_seconds: float
    env: Mapping[str, str] = Field(default_factory=dict)


class RunCheckArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
```

`id` 使用稳定的短标识规则；`argv` 只接受当前 Python 解释器配合 `-m`、`-c` 或项目相对 `.py` 入口；timeout 使用一个小的正数范围。`env` 是可信宿主冻结的最小补充环境，不接受模型输入。registry 只持有 `Mapping[str, CheckDefinition]` 的只读快照。

### 2.2 工具注册

`build_collaboration_registry()` 增加可选 `checks` 参数。Planner 与 Generator 忽略该参数；Evaluator 在映射非空时注册 `RunCheckTool`，否则保持现有 `FileRead`、`FileList`、`SubmitEvaluation` 精确集合。CLI/HTTP request body、checkpoint 和 collaboration state 均不存储检查定义。

角色 Task 的 `ToolContext.allowed_root` 已指向真实项目根。`RunCheckTool` 只读取它来创建副本，不向模型回显绝对路径。工具自身不调用普通 `ExecTool` 或 executor backend，避免复用允许模型代码的接口。

### 2.3 临时副本

每次检查创建独立 `TemporaryDirectory(prefix="forgeagent-check-")`。使用标准库 `shutil.copytree(..., dirs_exist_ok=True, ignore=...)` 复制普通文件与目录，固定排除：

- `.git`、`.forgeagent`；
- `.venv`、`venv`、`node_modules`；
- `__pycache__`、`.pytest_cache`、`.ruff_cache`、`.mypy_cache`；
- `dist`、`build`、`*.pyc`。

复制前拒绝全部 symlink；FIFO、socket、device 等特殊文件同样拒绝。这样避免复制后 symlink 重绑定、循环和宿主路径回指。失败返回固定 `copy_error`，不执行检查。

### 2.4 子进程与输出

`subprocess.Popen` 使用：

- `shell=False`，父进程启动专用 `_check_worker`，只转发已验证的 Python invocation；
- `cwd` 为临时副本；
- 环境从固定 allowlist（`PATH`、locale、必要的临时目录）加 definition.env 组成，不继承 credential；
- worker 复用 restricted audit hook：禁止副本外文件内容访问、目录枚举和路径变更；
- POSIX 使用 `start_new_session=True`；Windows 当前仅用 terminate/kill 兼容分支；
- worker 的 audit hook 拒绝全部 `socket.*`、spawn/fork/exec 和进程信号控制事件；
- stdout/stderr 走 pipe，由后台 drain 线程只保留有界 head/tail，超额数据立即丢弃；主循环同时检查 timeout 与 `cancel_event`。

timeout 或 cancel 时终止整个进程组，短 grace 后无条件尝试 group SIGKILL，避免 leader 先退出而顽固 descendant 存活。返回结果包含 `status`（passed/failed/timeout/cancelled）、`exit_code`、`duration_ms` 和有界 stdout/stderr。每个流最多 16 KiB，输出经过 secret/path masking。

### 2.5 取消传播

`ToolContext` 增加只读 `cancel_event`，由 `Task`/`Step` 现有 cancel event 传入。只有 `RunCheckTool` 使用它主动终止子进程；其他工具行为不变。协作 runner 在构造每个角色和每次 rejection 前再次检查 cancel，避免取消后创建新 client/Task。

同步 provider 和 MCP 调用没有安全异步强杀句柄，继续依靠现有 request/call timeout。调用返回或 timeout 后，Step/Task/Loop/Collaboration 在下一个安全边界发布 cancelled，不把 cooperative cancel 表述成即时终止。

## 3. MCP hung-call 回归

删除 `test_hung_call_times_out` 的永久 skip 和省略体。测试启动现有本地 stdio fixture 的 `hang_on_call` 模式，让真实 MCP session 的 `call_tool` 永不返回，并使用短 `call_timeout`。断言：

- 同步 `call_tool` 在宽松的总墙钟上限内返回 `ok=False`；
- public text 是固定 timeout，不含内部异常或 secret；
- manager generation/session 未被迟到结果覆盖；
- `close()` 在 shutdown deadline 内返回。

若测试暴露实现缺陷，只在现有 `_call_tool` deadline/ownership 路径做最小修复，不新增线程池或 watchdog manager。

## 4. 搜索 fallback

把一次请求提取为私有 `_search_engine(query, max_results, engine)`，返回 `(results, error_kind)`。`search_with_status()` 构造固定顺序：配置首选引擎，然后是另一个内置引擎；最多两次，不接受用户提供 URL 或动态 engine 列表。

首选网络失败、非 200、blocked 或零结果都会尝试备用。最终结果优先级：任一有结果即成功；否则任一 blocked → `blocked`；否则任一 unavailable → `unavailable`；两次均成功但零结果 → `( [], None )`。每次 `_search_engine` 都独立调用 `guarded_urlopen`，所以 fallback 不复用或绕过已校验连接。

## 5. 真实证据与 P3 裁决

### 5.1 真实模型

使用现有配置解析器和 runner，不打印或复制 API key。运行既有 5 项 real-model golden；另选一个小型、无副作用、可客观判定的代码任务，分别执行 single 与 Triad，并执行一次 credentialed Evaluator。报告记录模型 ID、通过/失败、rounds、usage 是否可用和稳定失败原因，不把样本结果外推为普遍质量保证。

### 5.2 Container/MCP

在 Docker daemon 和镜像可用时运行 `tests/test_container_backend.py` 全部真实集成测试。当前主机没有 Podman 或 Linux 原生环境时只记录缺口，不增加未经验证的 Podman 兼容代码。MCP 新 hung-call 测试必须在基础 CI 中运行，不再算环境 skip。

### 5.3 P3

- native OpenAI tool-call 流式碎片聚合已有 `tests/test_streaming.py` 回归，标记已完成；
- 持久 REPL 历史仅在用户明确需要跨会话历史且定义隐私/清理策略时重开；
- 语义摘要仅在 sliding window 的任务成功率或 token 成本有可重复退化时重开；
- 音视频输入仅在目标 provider 均有稳定标准字段和真实任务时重开；
- 响应侧多模态仅在协议、CLI 展示和 artifact 生命周期被明确需求驱动时重开。

## 6. 测试与完成门禁

每项产品行为均严格 RED→GREEN。专项至少覆盖：schema 注入拒绝、默认 registry、unknown ID、真实项目不变、symlink/special file、副本 cwd/env、pass/fail/timeout/cancel、输出上限/secret/path masking、取消不启动下一角色、MCP hung-call、搜索 fallback 顺序和错误优先级。

最终运行完整 pytest、Ruff format/check、离线 golden 20/20、wheel/sdist、OpenSpec strict 和 diff check。真实模型与 Docker 证据单列；外部环境失败不得改写离线门禁结论。

## 7. Implementation Divergence

- MCP hung-call 最终采用真实本地 stdio fixture 的永不返回工具，而非 loop fake session；它仍是
  快速、无公网的确定性回归，并覆盖更多真实 SDK 生命周期。
- POSIX process-group 终止已验证；Windows 仅保留 `terminate/kill` 兼容分支，未验证完整子树
  终止，不把设计中的 `CREATE_NEW_PROCESS_GROUP` 写成已交付保证。
- 真实模型外发命令因缺少对仓库派生 payload/destination 的具体授权被安全审查拒绝；验证报告
  将其记为未验证，而不是把凭证存在或命令尝试记作模型通过。
- PEP 578 只覆盖运行时发出的审计事件；未发出事件的 metadata syscall 与 native/kernel
  bypass 保持为明确残留风险，不宣称 sealed sandbox。

# M8 设计草稿：container sandbox（OS 级隔离）

> 状态：**已评审**（2026-07-11 §五 8 项裁决全部确认，另追加裁决 9：/proc、/sys 信息暴露需适当防御——见 §五.9 与 T9b）。进 Phase 0 spike。
> 范围（ACTION_PLAN.md M8 行）：container sandbox（OS 级隔离）；golden 任务集随任务扩展。
> 契约基准：不改 `model-client-contract.md` 与 `text-protocol-spec.md`（协议层对档位无感知）；扩展 `threat-model.md`（container 档从"占位"变为实装，原文多处写 "M10，待定或不做"，本里程碑将其提前到 M8 实装并同步措辞）。
> 参考来源：本项目自己的 `RestrictedBackend` + `_sandbox_worker`（M4 交付）——container 后端是同一后端接口的第三个实现，agent 无对应物（它完全没有 sandbox），本里程碑没有外部借鉴对象。

## 一、结论先行

M8 的重心是**把 threat-model 里预留的第三档 `container` 从占位变成实装**：同一个 `ExecutorBackend` 接口、同一个每块一次往返的 JSON worker 协议，把 spawn 方式从"本机子进程"换成 "`docker run` 一次性容器"。架构上是纯增量——不改 executor 抽象、不改 Step/Task、不改文本协议，新增一个 `ContainerBackend` 类 + `Tier` 加一个取值 + CLI/配置接线。

三个让这件事变得便宜的既有事实（已实证核查）：

1. **worker 零第三方依赖**：`_sandbox_worker.py` 只 import stdlib + `forgeagent.runtime`（纯 typing）。因此容器镜像用裸 `python:3.11-slim` 即可，把这两个模块只读挂载进容器就能跑，不需要构建自定义镜像、不需要在容器里 pip install。
2. **协议天然跨 spawn 方式**：restricted 的"stdin 喂 `{code,state,...}` JSON → stdout 收 result frame"是一次性往返、无长连接，`docker run -i` 的 stdin/stdout 语义与 `subprocess.run` 完全同构。
3. **路径透明可以保住**：Docker 允许把宿主目录挂载到容器内的**相同路径**（`-v $root:$root`）。LLM 生成的代码引用的是宿主路径，挂同路径后无需任何路径翻译——这是本设计消除"container 档要重写提示词/协议"风险的关键一招。

安全语义（相对 restricted 的实质增强）：容器内**不装 audit hook**——隔离由 OS 层承担（mount namespace 决定可见文件系统、`--network none` 断网、`--pids-limit` 防 fork 炸弹、`--memory/--cpus` 硬限、`--cap-drop ALL` + 非 root 用户 + 只读 rootfs 收缩攻击面）。restricted 挡不住的 `ctypes` 直调 syscall、native 代码逃逸，在 container 档被 namespace 拦在容器里——它能碰的最坏结果就是 allowed_root 挂载点本身。

## 二、现状与增量（对照自家 M4 实现逐项判定)

| 既有机制 | M8 处置 | 理由 |
|---|---|---|
| `ExecutorBackend.execute(code, runtime) -> ExecResult` 抽象 | **原样复用** | B2 决策"同一后端接口换更强隔离实现，架构不推倒"正是为今天准备的 |
| `_sandbox_worker` JSON 单轮往返协议（stdin/stdout） | **原样复用** | `docker run -i` 与 `subprocess.run(input=...)` 管道语义同构；worker 代码一行不改 |
| worker 内 `_install_audit_hook`（路径白名单/禁网/禁 spawn） | **container 档跳过**（payload 加开关） | 容器内 OS 隔离已兜底；容器内代码 spawn 子进程/联本地回环是无害的（namespace 内），保留 audit hook 反而造成假阴性（如容器内合法多进程数据处理被拦） |
| `_apply_rlimits`（CPU/内存） | **container 档跳过** | 由 `--memory`/`--cpus`/`--pids-limit` 在 OS 层实现，比进程内 rlimit 更硬（RLIMIT_AS 在 macOS 上本就不可靠，容器统一跑 Linux 后彻底绕开该平台差异） |
| `scrub_environment()`（restricted spawn 前洗 env） | **container 档天然满足 + 保留白名单机制** | `docker run` 默认不继承宿主 env——从"洗掉黑名单"升级为"默认全无、按需白名单注入"，更强 |
| `mask_secrets()` 输出掩码 | **原样复用** | 防御深度不因档位而省略；`_mask_result` 在主进程侧，对 backend 无感 |
| 跨块状态 JSON 化 + `dropped_state_keys` | **原样复用** | 同一 worker 同一语义 |
| 超时强杀（`subprocess.run(timeout=)`） | **改造**：超时后杀 docker CLI 客户端**不等于**杀容器，需显式 `docker kill <name>` | 这是 restricted→container 唯一有陷阱的差异点，Phase 0 spike 必须实测（见 §六死亡矩阵） |

## 三、架构设计

### 3.1 ContainerBackend（executor.py 新增类）

```python
class ContainerBackend(ExecutorBackend):
    """Per-block one-shot container backend (container tier). Each execute() runs
    `docker run --rm -i ...` with the same JSON worker protocol as RestrictedBackend;
    isolation is OS-level (namespaces), not the audit hook."""

    def __init__(self, *,
                 allowed_root: str | None = None,
                 image: str = "python:3.11-slim",
                 timeout_seconds: float = 60.0,
                 memory_mb: int = 512,
                 cpus: float = 1.0,
                 pids_limit: int = 64,
                 container_cli: str = "docker",   # podman 兼容同一 CLI 约定
                 secret_values: set[str] | None = None):
        ...
```

每次 `execute()` 组装的命令（要点，最终 flag 以 Phase 0 spike 实测为准）：

```
docker run --rm -i --name forgeagent-<uuid>
  --network none                      # 断网（比 restricted 的 audit 拦截更硬）
  --memory <mem> --cpus <cpus> --pids-limit <n>
  --cap-drop ALL --security-opt no-new-privileges
  --read-only --tmpfs /tmp            # rootfs 只读，临时区走 tmpfs
  --user <uid>:<gid>                  # 宿主当前 uid/gid，非 root（挂载文件属主自然对齐）
  -v <allowed_root>:<allowed_root>    # 同路径挂载，路径透明（rw）
  -v <forgeagent_pkg>/_sandbox_worker.py:/opt/fa/forgeagent/_sandbox_worker.py:ro
  -v <forgeagent_pkg>/runtime.py:/opt/fa/forgeagent/runtime.py:ro
  -e PYTHONPATH=/opt/fa
  -w <allowed_root>
  python:3.11-slim python -m forgeagent._sandbox_worker
```

（`/opt/fa/forgeagent/__init__.py` 的空文件问题：挂载一个 tmp 目录构造的最小包骨架，或改用 `-v` 挂三个文件——Phase 0 定，属实现细节非设计分歧。）

- **stdin/stdout**：payload/result frame 走 `docker run -i` 的管道，与 restricted 完全同一编解码路径；`ContainerBackend._run()` 与 `RestrictedBackend._run()` 的差异只在命令行组装与超时杀法，共享的解析/状态回收逻辑提取为模块级私有函数复用。
- **payload 增加 `"os_isolated": true`**：worker 据此跳过 `_install_audit_hook` 与 `_apply_rlimits`。restricted 不传即维持现状，worker 改动约 4 行。
- **超时**：`subprocess.run(timeout=)` 到点后先 `docker kill forgeagent-<uuid>`（best-effort，失败只记日志），再返回结构化超时错误。`--rm` 保证被 kill 的容器不残留。
- **docker 不可用**（未装/守护进程没起）：构造 `ContainerBackend` 时探测（`docker info` 一次，缓存结果），失败抛带修复指引的清晰错误（沿用 RegistryError 风格的 CLI 退出码 2 路径），绝不静默降级到 restricted——**静默降档就是静默放宽安全边界**，违反 threat-model"隔离强度=档位"的一句话原则。
- **首次镜像拉取**：`docker run` 会自动 pull，首次可能数十秒且需要网络。启动前 `docker image inspect` 探测，镜像缺失时打印明确的"正在拉取/请先 `docker pull`"提示，而非无解释卡住。

### 3.2 Tier 接线（task.py / cli.py）

- `Tier = Literal["trusted", "restricted", "container"]`；`_backend_for_tier` 加一个分支。
- CLI `--tier` choices 加 `container`；新增 `--container-image`（默认 `python:3.11-slim`）透传。
- README 与 threat-model 的"各档隔离强度"声明同步：container 从"M10 待定"改为已实装档位，明确其不缓解项（见 §四）。

### 3.3 明确不做（v1 范围声明）

- **不做常驻容器 / 容器池**：维持"每块一个一次性容器"，与 restricted 的每块子进程语义一致（超时强杀不丢状态、无块间污染、无池管理复杂度）。容器冷启动实测预估 0.3–1.5s/块（Phase 0 量化），在 LLM 秒级延迟面前可接受；若实测显著超预期，升级为设计分歧再裁决。
- **不做自定义镜像构建**（Dockerfile/buildx）：裸官方镜像 + 只读挂载 worker 已够。用户要第三方库时可自备镜像经 `--container-image` 指定——这同时是"容器内装包"需求的答案（T4 的确认门在容器档退化为"镜像里有什么就用什么"，运行时 pip 会被 `--network none` 挡死，行为正确且无需新代码）。
- **不做 podman/OrbStack 的专门适配**：`container_cli` 参数留了口子（两者 CLI 兼容 docker），但不测试不承诺。
- **不做 Windows 原生容器**：docker 容器统一跑 Linux（Docker Desktop on macOS/Windows 亦然），跨平台差异反而比 restricted 更小。
- **不做网络 Broker**：container 档同样默认断网，Broker 依旧留位不实装（与 §九-B1 裁决一致）。

## 四、threat-model 增量（T1–T7 在 container 档的落点）

| # | restricted 落点 | container 落点 | 增强/差异 |
|---|---|---|---|
| T1/T2 读写越权 | audit hook + realpath 白名单（Python 层） | mount namespace：容器内**根本不存在** allowed_root 之外的宿主文件系统 | 从"拦截访问"升级为"不可见"；native 代码也逃不出 |
| T3 出网 | audit hook 拦 socket 事件 | `--network none`：无网络设备 | ctypes 直调 socket syscall 也没有可用网卡 |
| T4 装包 | spawn+网络双拒（de facto） | `--network none` 挡 pip；镜像自备库是受支持路径 | 语义更清晰 |
| T5 提示注入 | 后端兜底 | 同左，兜底更硬 | — |
| T6 失控/fork | 超时 SIGKILL + rlimit（Unix） | 超时 `docker kill` + `--pids-limit` + `--memory`/`--cpus` | 全平台一致的硬限（不再有 Windows/macOS rlimit 缺口） |
| T7 动态导入绕过 | 静态告警 + 后端兜底 | 同左；容器内导入什么都无所谓，触达不了宿主 | — |
| **新增 T9a** | — | **容器逃逸**：内核漏洞、docker 守护进程漏洞、挂载点配置错误（如误挂 `/`）| 缓解：`--cap-drop ALL`/no-new-privileges/非 root/只读 rootfs 收缩攻击面；allowed_root 由主进程 realpath 后传入且唯一 rw 挂载；**不缓解**内核 0-day——诚实声明 container 档是"OS 级隔离"，不是"虚拟机级" |
| **新增 T9b**（裁决 9） | — | **`/proc`/`/sys` 信息泄露**：容器默认能看到部分 procfs/sysfs 内容（内核版本、CPU/内存拓扑、网络栈参数、`/proc/self` 环境等），可用于指纹宿主环境、辅助内核漏洞利用定位 | 缓解（适当防御，不追求密封）：① `--security-opt no-new-privileges` + 非 root 已限制可读子集；② 用 `--tmpfs` 或空 bind-mount **遮蔽高信息量路径**——`/proc/cpuinfo`、`/proc/meminfo`、`/sys` 整棵（`/sys` 对纯 Python 计算任务无正当用途，整棵遮蔽或依赖 runtime 默认只读）；③ `/proc` 本体不能整棵遮（Python 运行依赖 `/proc/self`），保留但依托 docker 默认的 masked paths（docker 默认已 mask `/proc/kcore`、`/proc/keys` 等）；④ Phase 0 D9 实测默认暴露面，按实测结果定最终遮蔽清单——**先测后遮，不凭想象列清单**。**不缓解**：/proc/self 自身信息（进程自省是合法需求）；侧信道级指纹。 |

## 五、开放裁决（8 项，需用户确认后进 Phase 0）

1. **容器生命周期**：每块一次性容器（推荐，语义与 restricted 一致、实现最简）vs 每任务常驻容器 + `docker exec`（省冷启动但引入池管理/崩溃恢复/状态残留）。**建议：每块一次性。**
2. **容器运行时对接方式**：`docker` CLI 子进程（推荐，零新依赖、podman 天然兼容）vs `docker` Python SDK（新依赖 ~4MB，API 更结构化但绑死 docker）。**建议：CLI 子进程。**
3. **默认镜像**：`python:3.11-slim`（推荐，~50MB，官方维护）；用户可 `--container-image` 覆盖。**建议：接受。**
4. **docker 缺席行为**：报错退出（推荐，拒绝静默降档）vs 警告后降级 restricted。**建议：报错退出。**
5. **路径策略**：同路径挂载保持路径透明（推荐）vs 挂 `/workspace` + 路径翻译层。**建议：同路径。**
6. **容器内 audit hook**：跳过（推荐，OS 层已兜底，避免容器内合法 spawn/回环被误拦）vs 双保险保留。**建议：跳过——保留会让"容器内多进程处理数据"这类合法模式失效，且防御纵深收益趋零（能绕 hook 的 native 代码正是 container 档要接住的，靠的是 namespace 不是 hook）。**
7. **golden 扩容规模**：+20 → **320 个**（G301–G320，8/5/4/2/1 精确维持 40/25/20/10/5% 配比），container 相关场景放"执行/边界"类（一次性容器状态跨块、断网拦截、pids 硬限、镜像缺失报错、docker 缺席报错、同路径挂载读写等）。**建议：+20。**
8. **测试策略**：container 集成测试**本机有 docker 则跑、无则 skip**（`pytest.mark.skipif(shutil.which("docker") is None ...)` + `docker info` 探测），与"基础 CI 无 key 可跑"原则并列一条"基础 CI 无 docker 可跑"；escape tests 加 container 版 T1/T3/T6/T9（挂载外不可见、无网、pids 限制、非 root 断言）。**建议：接受。**
9. **（2026-07-11 用户追加）`/proc`/`/sys` 信息暴露适当防御**：容器默认可见部分 procfs/sysfs 内容，需遮蔽高信息量路径（`/sys` 整棵、`/proc/cpuinfo`/`/proc/meminfo` 等），`/proc/self` 保留（Python 运行依赖），最终遮蔽清单以 Phase 0 D9 实测暴露面为准。详见 §四 T9b。

> **裁决记录（2026-07-11）**：1–8 全部按建议通过，第 9 项为用户追加要求。

## 六、Phase 0 spike（裁决通过后、编码前）

最小脚本实测并记录（对齐 M6/M7 "wire 层先核实再写代码"的教训）：

- D1 冷启动延迟：`docker run --rm python:3.11-slim python -c 'print(1)'` 计时 ×5。
- D2 stdin/stdout 往返：`docker run -i` 喂 JSON 收 JSON，验证无缓冲/编码陷阱。
- D3 同路径挂载：宿主临时目录挂同路径，容器内读写、宿主侧验证内容与属主。
- D4 超时杀死矩阵：死循环块 → 客户端超时 → `docker kill` → `docker ps` 断言无残留容器。
- D5 `--network none` 下 socket connect/getaddrinfo 的实际报错形态（决定 `_blocked` 判定字符串）。
- D6 `--pids-limit` 下 fork 炸弹的实际失败形态。
- D7 非 root `--user` + 只读 rootfs 下 worker 正常跑通（stdlib import 无权限问题）。
- D8 worker 包骨架挂载方案定型（目录 vs 逐文件）。
- D9（裁决 9）`/proc`/`/sys` 默认暴露面盘点：非 root + cap-drop ALL 下实际可读哪些高信息量路径（cpuinfo/meminfo/sys 树/net 参数），据此定遮蔽清单；再验证遮蔽后（tmpfs/空挂载覆盖）worker 与典型 Python 任务仍正常运行。

## 七、实施 Phase 划分

- Phase 0：§六 spike（8 项全过留实测记录进本文档 §八）。
- Phase 1：`ContainerBackend` + worker `os_isolated` 开关 + restricted/container 共享逻辑提取；单测（mock docker CLI 层）+ 有 docker 时的真实集成测试。
- Phase 2：Tier/CLI/配置接线（`--tier container`、`--container-image`、docker 探测报错路径）；CLI 测试。
- Phase 3：escape tests container 版（T1/T3/T6/T9）+ threat-model/README 文档同步。
- Phase 4：golden G301–G320 + 配比核对表更新。
- Phase 5：三评审（技术方案/对抗性代码评审/验收）+ `milestones/milestone_008.md` + `latest` 更新。

## 八、Phase 0 spike 实测记录（2026-07-11，Docker Desktop 29.2.1 / linux-aarch64 / linuxkit 6.12.68）

全部 9 项完成。逐项结果与设计影响：

- **D1 冷启动 ✅**：`docker run --rm python:3.11-slim python -c 'print(1)'` ×5 = 0.23/0.20/0.19/0.19/0.20s。**远低于预估的 0.3–1.5s**，每块一次性容器的延迟顾虑解除（镜像已在本地时）。
- **D2 stdin/stdout 往返 ✅**：`docker run -i` 管道喂 JSON 收 JSON 无缓冲/编码问题，与 `subprocess.run(input=...)` 行为同构。
- **D3 同路径挂载 ✅**：宿主目录 `-v $ROOT:$ROOT` + `--user $(id -u):$(id -g)`，容器内读宿主文件、写新文件，宿主侧属主为当前用户（`admin wheel`），无 root-owned 残留。
- **D4 超时杀死矩阵 ✅（陷阱实证）**：D4b 证实**只杀 docker CLI 客户端进程后容器继续存活**（`docker ps` 仍在跑）——设计中的显式 `docker kill <name>` 步骤是必需的，不是防御性冗余。`docker kill` 后容器立即消失（`--rm` 生效，`docker ps -a` 计数 0），CLI 客户端退出码 137。
- **D5 断网报错形态 ✅**：`--network none` 下 `socket.connect` → `OSError [Errno 101] Network is unreachable`；`getaddrinfo` → `gaierror [Errno -3] Temporary failure in name resolution`。注意**不是 PermissionError、消息里没有 "denied"**——escape test 的 `_blocked` 判定要为 container 档单列判定字符串（`Network is unreachable` / `name resolution`），不能复用 restricted 的 `restricted:`/`denied` 标记。
- **D6 fork 炸弹 ✅**：`--pids-limit 16` 下第 15 次 fork 失败，`BlockingIOError [Errno 11] Resource temporarily unavailable`。硬限生效，失败形态是可捕获异常而非杀容器。
- **D7 全加固 flag 下 worker 可跑 ✅**：`--user 非root --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges --network none` 组合下 stdlib import 与 tempfile 写 /tmp 全部正常。
- **D8 worker 包骨架挂载定型 ✅**：方案 = tmp 目录构造 `forgeagent/{__init__.py(空), _sandbox_worker.py, runtime.py}` 三文件骨架，`-v <dir>:/opt/fa:ro -e PYTHONPATH=/opt/fa`，`python -m forgeagent._sandbox_worker` 端到端跑通：真实 payload（含 `set_state`/`get_state`）返回正确 result frame `{"success": true, "stdout": "42\n", ..., "state": {"n": 21}}`。骨架目录由 ContainerBackend 构造时一次性搭好（tempfile.mkdtemp），close/析构时清理。
- **D9 /proc//sys 暴露面与遮蔽 ✅（裁决 9 落地方案实测定型）**：
  - **默认暴露面（非 root + cap-drop ALL + read-only）**：`/proc/cpuinfo`、`/proc/meminfo`、`/proc/version`（内核版本 6.12.68-linuxkit）、`/proc/net/dev`、`/proc/net/tcp`、`/proc/1/environ`（=容器自身 PID1 env，非宿主）、`/sys` 整棵（cpu 拓扑、cgroup 限额 `memory.max` 等）均可读。docker 默认 masked paths 生效：`/proc/kcore`、`/proc/keys` 读出为空。
  - **关键限制（实测发现）**：**runc 禁止向 `/proc` 内部路径做自定义 bind-mount**（`cannot be mounted because it is inside /proc` 的 proc-safety 检查，容器直接拒绝启动）——设计稿里"用空挂载遮 `/proc/cpuinfo`/`meminfo`"的选项②对 /proc **不可行**，先测后遮避免了把不可行方案写进代码。
  - **定型方案**：① `--tmpfs /sys`（可加 `:ro`）整棵遮蔽 `/sys`——实测 `listdir /sys` 为空、stdlib 正常；② `/proc` 依托 docker 默认 masked paths（kcore/keys 等已遮）+ 非 root 限权，`cpuinfo`/`meminfo`/`version`/`net` 的剩余可读性**如实写进 T9b 的"不缓解"声明**（信息级泄露：CPU 型号、内存总量、linuxkit 内核版本——无宿主路径、无宿主 env、无宿主网络连接内容，风险为环境指纹辅助，接受）；③ `/proc/*/environ` 只含容器自身 env，而 container 档 env 是默认全无+白名单注入（§二），故无 secret 可泄。
  - T9b 缓解表述按此更新：遮蔽 `/sys` 整棵 + docker 默认 /proc masks + env 白名单注入；不缓解 `/proc` 基础信息（cpuinfo/meminfo/version/net 统计）。

**对设计的净影响**：①`_blocked` 判定字符串 container 档单列；②显式 `docker kill` 必需（D4b 实证）；③ run flags 定稿追加 `--tmpfs /sys`；④ T9b 缓解/不缓解清单按 D9 实测收敛。其余设计原样成立，可进 Phase 1。

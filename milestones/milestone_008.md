# 里程碑 M8: Container Sandbox（OS 级隔离）

- 状态: 已完成
- 起止: 2026-07-11 ~ 2026-07-11
- 对应 ACTION_PLAN 行: M8（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_007](milestone_007.md)

## 目标与范围

摘自 ACTION_PLAN.md §四 M8 行：

- 交付物：container sandbox（OS 级隔离）；golden 任务集适量扩展。
- 验证：—（未预设具体命令，由本里程碑自定义验收证据）。
- 门禁：视需求排期（弱门禁，不要求用户显式批准）。

设计依据：`docs/m8-container-sandbox.md`（含 §五 9 项裁决、§六/§八 Phase-0 spike 实测 D1-D9、§四 threat-model 增量 T9a/T9b）。

## 方案设计

9 项裁决（`docs/m8-container-sandbox.md` §五，2026-07-11 用户确认，1-8 按建议通过 + 用户追加第 9 项）：

1. **执行模型**：延续 B2（`docs/threat-model.md`）的"档位=执行机制"设计，新增 `container` 档——每个代码块起一个一次性（one-shot）容器，非常驻，语义与 `restricted` 的"每块新起子进程"一致，只是隔离手段从应用层换成 OS 级 mount namespace。
2. **Docker 接入方式**：CLI 子进程调用（`subprocess.run(["docker", "run", ...])`），不引入 Docker Python SDK 依赖——零新依赖，且天然兼容 podman 等 CLI 兼容实现。
3. **Worker 复用**：容器内运行同一份 `_sandbox_worker.py`（零第三方依赖），通过只读挂载一个临时构造的 package skeleton（`forgeagent/{__init__.py,_sandbox_worker.py,runtime.py}`）+ `PYTHONPATH` 注入，复用 `restricted` 档完全相同的 JSON stdin/stdout 协议——文本协议、Step/Task 循环、系统提示词零改动。
4. **应用层隔离开关**：`os_isolated=True` 时 worker 内部跳过 PEP 578 audit hook 与 rlimit 设置，因为容器本身（mount namespace/`--network none`/`--pids-limit`/`--memory`/`--cpus`）已提供更强隔离，应用层 hook 继续开启只会对容器内合法行为（如 multiprocessing）产生误伤。
5. **路径透明挂载**：`allowed_root` 以**相同路径**挂进容器（`-v $ROOT:$ROOT`），不做路径翻译——生成代码里引用的宿主路径在容器内原样可用，代码生成/提示词零改动。
6. **资源硬限制**：`--memory`/`--cpus`/`--pids-limit` 三项映射到构造函数参数，默认值 512m/1.0/64。
7. **加固标志集**：`--cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp --network none`，非 root 运行（POSIX 上用 `--user uid:gid`，Windows 无 `os.getuid` 时跳过）。
8. **失败即报错，不静默降级**：缺 docker CLI / daemon 未启动 / 镜像不存在，均抛 `ContainerRuntimeError`，绝不静默退回 `restricted` 或 `trusted`——延续 `docs/threat-model.md` 的核心原则"隔离强度 = 所选档位对应后端能提供的强度"。
9. **（用户追加）`/proc`/`/sys` 信息暴露适当防御**：容器默认可见部分 procfs/sysfs 内容，需遮蔽高信息量路径。Phase 0 spike D9 实测发现 runc 禁止对 `/proc` 内部路径做自定义 bind mount（"cannot be mounted because it is inside /proc"），故设计收敛为：`--tmpfs /sys:ro` 整棵遮蔽 `/sys`；`/proc` 依赖 docker 默认掩码（已验证 `/proc/kcore`、`/proc/keys` 默认为空）+ 非 root + `cap-drop ALL` + env 不继承宿主；`/proc/cpuinfo`/`meminfo`/`version`/`net/*` 等基础信息**明确不缓解**、作为指纹级残留风险诚实声明（详见 §四 T9b），不是"适当"要求的完全密封。

Phase 0 spike（`docs/m8-container-sandbox.md` §八，真机实测 Docker Desktop 29.2.1 / linux-aarch64 / linuxkit 6.12.68）关键发现：

- **D1** 冷启动 0.19-0.23s/次，优于设计估算，去除了 per-block 开销顾虑。
- **D4/D4b（对设计有净影响的关键发现）**：`kill -9` docker CLI 客户端进程**不会**杀掉容器（`docker ps` 确认容器仍在跑）——超时路径必须显式 `docker kill <name>`，且该调用本身需容错（守护进程若已挂起,kill 调用可能自身超时/失败）。
- **D5**：`--network none` 下 `connect()` 报 `OSError: Network is unreachable`、DNS 报 `gaierror: Temporary failure in name resolution`——与 restricted 档 audit hook 的 `PermissionError`/"denied" 字符串不同，container 档 T3 escape test 需要单独的错误匹配模式。
- **D6**：`--pids-limit 16` 下第 15 个 fork 报 `BlockingIOError: Resource temporarily unavailable`。
- **D9**：非 root + cap-drop ALL 下默认可读 cpuinfo/meminfo/version(=6.12.68-linuxkit)/net/dev/net/tcp/`/proc/1/environ`（容器自身空 env，非宿主）+ 整棵 `/sys`（含 cgroup limits）；`--tmpfs /sys` 验证后 `os.listdir('/sys')` 返回 `[]`，且不影响 worker 与典型 Python 任务运行。

对设计的净影响（§八 结论）：①`_blocked` 判定字符串 container 档单列；②显式 `docker kill` 必需；③ run flags 定稿追加 `--tmpfs /sys:ro`；④ T9b 缓解/不缓解清单按 D9 实测收敛，不做"看起来全密封但实际做不到"的假承诺。

## 子任务清单

- [x] Phase 0：设计文档 `docs/m8-container-sandbox.md` 撰写 + 用户评审（9 项裁决全部确认）+ Phase-0 spike D1-D9 全部真机实测（非模拟）
- [x] Phase 1：`ContainerBackend` 骨架——`_verify_container_runtime`（CLI/daemon/镜像三级探测，失败即报错不降级）、`_build_worker_skeleton`（临时目录构造只读挂载包）、`os_uid_gid`（跨平台非 root 探测）
- [x] Phase 2：`_run_command` 加固标志集组装 + `_run` 执行主体（stdin/stdout JSON 协议、超时显式 `docker kill`、`_parse_worker_frame`/`_result_from_frame` 共享解析逻辑，`RestrictedBackend` 同步改为复用这两个共享函数）
- [x] Phase 3：接线——`task.py` `Tier` 增加 `"container"` + `_backend_for_tier` 路由 + `Task.container_image` 参数；`cli.py` `--tier container` + `--container-image` + `ContainerRuntimeError` 顶层捕获
- [x] Phase 4：文档同步——`docs/threat-model.md`（T9a 容器逃逸 + T9b `/proc`/`/sys` 泄露）、`README.md`（container 档说明 + 示例命令）、`docs/golden-tasks-seed.md`（G301-320，配比精确维持）
- [x] Phase 5：对抗性代码评审（委派 general-purpose subagent）+ 7 个发现全部修复（2 major + 3 minor + 2 nit）
- [x] Phase 6：全量验证（pytest + ruff）+ 本里程碑文件收尾

## 交付物清单

- [x] `src/forgeagent/executor.py` — 新增 `ContainerBackend`（`__init__`/`_run_command`/`_run`/`close`）、`ContainerRuntimeError`、`os_uid_gid`、`_verify_container_runtime`、`_build_worker_skeleton`；新增共享解析函数 `_parse_worker_frame`/`_result_from_frame`（`RestrictedBackend` 同步复用，去重）
- [x] `src/forgeagent/_sandbox_worker.py` — 新增 `os_isolated` payload 字段，为真时跳过应用层 audit hook + rlimit（容器已提供更强隔离）
- [x] `src/forgeagent/task.py` — `Tier` 增加 `"container"`；`_backend_for_tier` 路由；`Task.__init__` 新增 `container_image` 参数；新增 `Task.close()`（释放 backend 资源，如临时 skeleton 目录）
- [x] `src/forgeagent/cli.py` — `--tier` choices 扩展、`--container-image` 参数、`ContainerRuntimeError` 顶层捕获（exit code 2）、`run_once()` 补 `try/finally: task.close()`
- [x] `tests/test_container_backend.py` — 新增，两组测试：无 docker 依赖的命令组装/错误路径单测（4 个，含 colon 校验）+ docker 依赖的集成/逃逸测试（10 个：正常执行/跨块状态/同路径挂载/超时杀容器/异常捕获/T1 宿主文件不可见/T3 断网/T6 pids-limit/T9 非root+sys遮蔽/T9 无宿主 secret env）
- [x] `docs/m8-container-sandbox.md` — 设计文档（9 裁决 + Phase-0 spike 实测 D1-D9 + threat-model 增量）
- [x] `docs/threat-model.md` — container 档表格填实、T9a（容器逃逸）/T9b（`/proc`/`/sys` 泄露）新增行
- [x] `README.md` — container 档说明段落 + 示例命令
- [x] `docs/golden-tasks-seed.md` — G301-320（20 个，8/5/4/2/1 精确维持 40/25/20/10/5% 配比），总数扩到 320

## 三次评审

### 技术方案评审

- [x] 9 项裁决逐一对照实现代码确认落地，无方案偏离
- [x] Phase-0 spike 发现的 4 项净影响（D4b 显式 kill、`_blocked` 判定字符串单列、`--tmpfs /sys:ro` 追加、T9b 清单收敛）均已体现在最终实现与文档中，不是"先设计后忽略实测"

### 代码评审

- [x] 委派 general-purpose subagent 对抗性复审本里程碑 diff（环境无 code-reviewer 类型，同 M6/M7 做法）
- [x] 发现 7 个问题，全部确认为真实问题并修复：
  1. **major** — 未信任的容器 worker stdout 若被模型代码写入非 dict 形状内容并 `os._exit(0)`，会导致 `_parse_worker_frame`/`_result_from_frame` 抛出未捕获异常（`AttributeError`/`KeyError`/`TypeError`）逃出 `execute()`，可致主进程崩溃。修复：`_parse_worker_frame` 增加 `isinstance` 校验，`_result_from_frame` 全部改用防御性 `.get()` + 类型强转，异常路径统一收敛为结构化 `ExecResult(success=False)`
  2. **major** — `ContainerBackend.close()` 从未被调用，导致临时 worker skeleton 目录在每次 `Task` 创建时泄漏，且每次都重新探测 docker（`docker info` + `image inspect`）。修复：`ContainerBackend.__init__` 内 `atexit.register(self.close)`；新增 `Task.close()` 委派给 backend；`cli.py` `run_once()` 用 `try/finally` 包裹 `task.run(goal)`
  3. **minor** — 超时路径里的 cleanup `docker kill` 调用未加保护，若守护进程本身已挂起（超时的可能根因），kill 调用可能自身抛 `TimeoutExpired` 逃出 `execute()`。修复：包一层 `try/except (subprocess.TimeoutExpired, OSError): pass`
  4. **minor** — `allowed_root` 路径含冒号（macOS 合法路径字符）会破坏 `-v src:dst` 挂载语法，静默挂错路径。修复：`__init__` 内提前校验，含冒号即抛 `ContainerRuntimeError`
  5. **minor** — `test_timeout_kills_container_and_next_block_runs` 在 `docker kill` 后立即单次快照断言容器已移除，但 `--rm` 移除是异步的，存在竞态。修复：改为最多 10 次 × 0.5s 轮询
  6. **nit** — `test_t1_host_filesystem_not_visible` 打印了 `~/.ssh` 探测结果但从未断言。修复：补 `assert "home: False" in result.stdout`
  7. **nit** — `test_run_command_hardening_flags` 标了 `@docker_required` 但实际只测命令组装，不需要真实 docker，导致 docker-less CI 丢失该项覆盖。修复：改签名为 `(tmp_path, monkeypatch)`，内部 `monkeypatch.setattr` 打桩 `_verify_container_runtime` 为空操作
- [x] 无遗留未处理发现

### 验收评审

- [x] ACTION_PLAN M8 行"验证"列（—，自定义证据）：全量单测 + 真实 docker 集成/逃逸测试两类证据满足：
  ```
  $ .venv/bin/python -m pytest tests/ -q -rs
  313 passed, 1 skipped in 33.11s
  SKIPPED [1] tests/test_mcp_manager.py:274: hang test is slow; covered by the Phase-0 spike (§八 D4)
  $ .venv/bin/ruff check src/ tests/
  All checks passed!
  ```
  （唯一 skip 是 M7 遗留的慢速 MCP hang 测试，与本里程碑无关；容器相关的全部集成/逃逸测试在本机 Docker Desktop 29.2.1 上真实跑通，非 mock）
- [x] ACTION_PLAN M8 行"门禁"列（视需求排期，弱门禁）：满足。golden 集扩到 320（`grep -oE '\bG[0-9]+\b' | sort -u -V | wc -l` = 320），配比核对表 128/80/64/32/16 = 40/25/20/10/5% 精确匹配
- [x] Phase-0 spike 全部 9 项（D1-D9）均有真机实测记录，非假设性设计
- [x] 用户追加裁决 9（`/proc`/`/sys` 适当防御）已落地为 `--tmpfs /sys:ro` + docker 默认掩码 + T9b 诚实声明缓解/不缓解边界，不是过度承诺的"全密封"
- [x] 无未满足项

## 遗留问题

- [ ] T9b 的"不缓解"清单（`/proc/cpuinfo`/`meminfo`/`version`/`net/*` 等基础信息）属于已知且诚实声明的残留风险 — 影响：容器内代码可获取宿主内核版本等指纹级信息，构成信息泄露但非直接的密钥/数据泄露 — 计划：暂不处理（runc 禁止 `/proc` 内部自定义挂载是运行时层限制，非配置疏漏），若后续需要更强遮蔽可考虑 gVisor/Kata 等替换运行时，超出本里程碑范围
- [ ] container 档目前只验证了本机 Docker Desktop（linux-aarch64 + linuxkit），未在 Linux 原生 docker 或 podman 上冒烟 — 影响：CLI 兼容性假设（decision 2）尚无跨平台实测证据 — 计划：留待有对应环境时补充验证，不阻塞 M8 收尾

## 续接指引

M8 已完成：新增 `container` 执行档，复用 `restricted` 档完全相同的 worker 协议与 JSON stdin/stdout 契约，隔离手段从应用层 audit hook/rlimit 换成 OS 级 mount namespace + docker 加固标志集（`--network none --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp --tmpfs /sys:ro --pids-limit`）。任务/CLI 层新增 `--tier container` + `--container-image`，缺 docker 时显式报错、绝不静默降级到更弱档位。Phase-0 spike 用真机验证了 9 项关键假设，其中 D4b（容器不会因杀死 CLI 客户端而终止,必须显式 `docker kill`）与 D9（runc 禁止 `/proc` 内部自定义挂载，只能靠 `--tmpfs /sys` + docker 默认掩码）是对最初设计的实质修正。对抗性代码评审发现并修复 7 个问题（2 个 major：未信任 worker 输出解析崩溃风险、`close()` 资源泄漏）。313 单测全绿 + 1 个与本里程碑无关的既有 skip，ruff 清。golden 集扩到 320，配比精确维持 40/25/20/10/5%。

M8 延续的约束：不硬编码厂商端点/key（container 档同样不涉及）；隔离强度=所选档位后端能提供的强度（container 档缺 docker 必须报错，不能悄悄退回 restricted）；三轮评审机制（含对抗性代码评审）在每里程碑收尾执行；secret 掩码机制（`secret_policy.py`）横跨所有 backend 生效，container 档同样受益于 docker run 不继承宿主环境这一天然屏障。

下一步可选方向（按 ACTION_PLAN 里程碑表）：**M9 流式 + 多模态** — `ModelClient.stream()`/`StreamEvent`、`ContentItem` 联合类型、`/model`/`/search`/`/mcp`/`/help` 内嵌指令；或 **M10 用量可观测性 + WebFetch/FileRead/FileWrite 工具生态扩展**（后者需要 SSRF 逐跳复检 + project-root 锁定，且在 restricted 档下 WebFetch/FileWrite 必须触发确认门）。M8 的 `ContainerBackend` 已就位，未来若 WebFetch/FileWrite 等新工具需要更强隔离，可直接选 `--tier container` 承载，无需新增执行机制。

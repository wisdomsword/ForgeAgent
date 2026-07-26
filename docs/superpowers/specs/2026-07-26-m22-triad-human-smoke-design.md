---
comet_change: add-m22-triad-human-smoke
role: technical-design
canonical_spec: openspec
---

# M22 Triad 人类冒烟测试技术设计

## 1. 目标

提供一个显式选择执行的一键命令：在隔离目录中运行现有真实模型 Triad 工作流，保留 Planner 原生人工确认，并自动验收协作协议和生成的 `moving_average` 产物。它是仓库验收工具，不是新的 ForgeAgent 产品命令。

## 2. 范围

本变更新增 `scripts/m22-triad-human-smoke.py`、对应离线测试和 README 入口。不修改 `src/forgeagent`、CLI 参数、模型注册表、协作状态 schema、identity、memory、HTTP 或依赖，也不比较 single 与 Triad 的质量。

## 3. 命令契约

README 记录以下命令：

```bash
uv run --offline python scripts/m22-triad-human-smoke.py
```

脚本根据自身路径定位仓库，并要求以下现有可执行文件存在：

- `.venv/bin/forgeagent`
- `.venv/bin/python`（允许虚拟环境的标准可执行 symlink）

默认模型如下：

- Generator：`claude-sonnet-5`
- Planner：`claude-haiku-4-5`
- Evaluator：`claude-haiku-4-5`

仅允许通过 `FORGEAGENT_M22_MODEL`、`FORGEAGENT_M22_PLANNER_MODEL` 和 `FORGEAGENT_M22_EVALUATOR_MODEL` 覆盖默认值。空值、控制字符或过长值必须在启动 ForgeAgent 前被拒绝。脚本不读取或打印凭证值，继续以现有客户端配置为权威来源。

## 4. 执行流程

在创建工作目录或调用真实模型前，脚本先确认 stdin 和 stdout 都是 TTY。非交互执行以退出码 2 结束，并说明 Planner 人工确认需要交互式终端。

交互执行时，脚本通过 `tempfile.mkdtemp(prefix="forgeagent-m22-human-", dir="/tmp")` 创建唯一目录，立即打印路径，并且永不自动删除。然后以该目录为 `cwd` 执行：

```text
.venv/bin/forgeagent
  --model <generator>
  --tier restricted
  --no-identity
  --no-memory
  run
  --mode triad
  --planner-model <planner>
  --evaluator-model <evaluator>
  --max-rejections 2
  <固定 moving_average 任务>
```

子进程继承 stdin、stdout 和 stderr，不使用 `capture_output`、pipe 或合成回答，因此现有 `approve plan? [y/N]` 仍是唯一的计划批准路径。restricted tier 触发的其他原生确认也保持原样。

## 5. 稳定状态验收

ForgeAgent 退出后，脚本只搜索 `<workdir>/.forgeagent/collaborations/*.json`，并要求恰好存在一个普通文件。`load_collaboration_state()` 使用标准库解析 JSON 并返回原始 `dict[str, object]`，不导入或调用 `CollaborationState.model_validate()`；`collaboration_failures()` 只校验本冒烟契约依赖的稳定字段投影，忽略 schema、usage、rounds 等无关字段。这样脚本不会复制完整持久化 schema，也不会因新增无关字段失效。所有已使用字段仍按严格 Python 类型检查，布尔值不能充当整数。

成功状态必须满足：

- `mode == "triad"`
- `collaboration_id` 是 32 位小写十六进制字符串
- `status == "completed"`
- `phase == "completed"`
- `stop_reason == "completed"`
- `plan` 是非空 acceptance item 列表，且 `plan_digest` 是 64 位小写十六进制字符串；脚本只验证摘要格式，不重算运行时 digest
- `generator_attempts >= 1`
- `evaluator_attempts >= 1`
- `last_evaluation` 非空、item ID 按相同顺序完整覆盖 plan，并且每一项的 `passed is True`

若持久状态的 stop reason 为 `needs_confirmation`，诊断应明确指出人工拒绝计划，而不是笼统归为模型失败。`invalid_role_submission` 必须原样显示为协议失败。其他失败只投影有长度上限的稳定字段：status、phase、stop reason 和非负计数器。不得回显目标、计划正文、verdict 证据、模型原始输出、产物内容或凭证。

## 6. 产物验收

只有状态验收通过后才执行产物命令：

1. 要求工作目录中的 `calc.py` 和 `test_calc.py` 都是普通文件。
2. 以继承终端输出的方式运行 `.venv/bin/python -m pytest -q`，并要求退出码为 0。
3. 捕获文本输出运行 `.venv/bin/python calc.py '[1,2,3,4]' 2`。
4. 要求 stderr 为空，将 stdout 解析为 JSON，并要求与 `[1.5, 2.5, 3.5]` 精确相等。

诊断中引用 CLI 输出前必须截断到固定长度。包装脚本不新增超时：底层模型和工具客户端继续使用现有超时策略，任意额外超时可能在用户审阅计划时误中断流程。

## 7. 结果与退出码

- `0`：协作状态和全部产物检查通过。
- `1`：ForgeAgent、计划批准、协作协议、生成文件、pytest 或 CLI 行为失败。
- `2`：真实模型执行前的本地预检失败，包括非 TTY、非法模型覆盖或项目虚拟环境可执行文件缺失。
- `130`：用户按 Ctrl-C 中断；若工作目录已经创建，仍打印保留路径。

创建目录后的每一种退出路径都打印 `workdir`。成功时额外打印 collaboration ID、Generator/Evaluator attempts、rejections 和 `PASS`。失败时只打印一个简洁的分阶段原因和 `FAIL`，不删除或改写生成产物。

## 8. 可测试性

脚本暴露少量标准库函数，不增加类层级：

- `build_forgeagent_command(forgeagent: Path, models: SmokeModels) -> list[str]`
- `load_collaboration_state(workdir: Path) -> dict[str, object]`
- `collaboration_failures(state: dict[str, object]) -> list[str]`
- `artifact_failures(workdir: Path, python: Path, run: RunCommand) -> list[str]`
- `run_smoke(config: SmokeConfig, run: RunCommand = subprocess.run) -> int`
- `main() -> int`

`SmokeModels` 与 `SmokeConfig` 使用 frozen dataclass，只为明确命令参数和测试注入依赖。`RunCommand` 是与 `subprocess.run` 兼容的 callable 类型别名；不新增 wrapper 类或依赖。

离线测试通过路径导入脚本并注入假 runner。fixture 只在 `tmp_path` 下写入合成状态与产物，不调用真实 ForgeAgent、不读取用户 HOME、不访问网络。合成 secret 放入不可信的 plan/evaluation/额外状态字段，验证稳定投影不会回显它；测试不要求脚本扫描或隐藏环境变量，因为真实模型执行需要继承用户已有配置。矩阵覆盖命令组装、成功验收、非 TTY 预检、计划拒绝、ForgeAgent 非零退出、零份/多份/损坏状态、非法计数器、缺文件、pytest 失败、stderr 输出、非法 JSON 和错误 moving-average 值。

## 9. 文档

README 在 M22 Duo/Triad 说明附近记录一键命令，并明确：

- 命令调用真实模型，可能产生费用；
- 必须在交互式终端执行并人工批准计划；
- 三个模型环境变量覆盖项；
- 成功和失败现场都会保留在 `/tmp`；
- 这是验收冒烟测试，不是质量 benchmark 或 CI 门禁。

## 10. 安全与失败边界

- 固定目标和参数数组通过不带 `shell=True` 的 `subprocess.run` 执行。
- 模型 ID 有长度和控制字符约束，且不会插入 shell 文本。
- 状态发现仅限脚本新建的隔离目录。
- 状态详情只投影稳定计数器，不打印不可信的计划或证据文本。
- 仅在用户请求的 restricted-tier 人类验收流程中执行生成代码；脚本不扩大 ForgeAgent sandbox 或确认策略。

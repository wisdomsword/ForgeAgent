---
change: add-m22-triad-human-smoke
design-doc: docs/superpowers/specs/2026-07-26-m22-triad-human-smoke-design.md
base-ref: 5e08c89ea70a9de83be8de0a4026ecf8f2ccbc39
---

# M22 Triad 人类冒烟测试实施计划

> **给 agentic workers：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实施本计划。所有步骤使用 checkbox 跟踪。

**目标：** 新增一个保留 Planner 人工确认的一键真实模型 Triad 冒烟脚本，并自动验收协作终态、生成文件、pytest 和 moving-average CLI JSON。

**架构：** 一个独立标准库 Python 脚本负责预检、创建 `/tmp` 隔离目录、以原生终端 stdio 运行现有 ForgeAgent CLI、读取单份协作状态并执行产物验收。离线 pytest 通过路径导入脚本和注入 fake `subprocess.run`，不调用真实模型、不读取用户 HOME、不访问网络。

**技术栈：** Python 3.11、标准库 `dataclasses/json/os/pathlib/stat/subprocess/sys/tempfile/unicodedata`、pytest、uv、ruff、OpenSpec/Comet。

## 全局约束

- 不修改 `src/forgeagent`、CLI 参数、运行时协议、模型注册表、持久化 schema 或依赖。
- 真实执行必须使用 `.venv/bin/forgeagent`、`.venv/bin/python`、`--tier restricted`、`--no-identity`、`--no-memory`、Triad 和 `--max-rejections 2`。
- stdin 或 stdout 非 TTY 时必须在创建工作目录和调用真实模型前以退出码 2 失败。
- Planner 计划只能通过原 CLI 人工确认；脚本不得自动输入 `y`，并保留 restricted tier 的其他原生确认。
- 成功和失败都保留工作目录；任何自动测试不得调用真实模型、访问网络、读取真实用户 HOME 或消耗凭证。
- 只打印有界稳定诊断，不回显 API key、目标、计划正文、verdict evidence、模型原始输出或产物正文。
- 写代码时遵循 YAGNI：不新增 argparse、wrapper class、配置文件、通用 helper 模块或第三方依赖。
- 保留所有无关 dirty-worktree 文件，每次提交只暂存本计划列出的文件。

## 计划文件结构

| 文件 | 职责 |
| --- | --- |
| `scripts/m22-triad-human-smoke.py` | TTY/模型/解释器预检、命令组装、隔离执行、状态与产物验收、结果摘要。 |
| `tests/test_m22_triad_human_smoke.py` | 按路径导入脚本，使用 fake runner 与 `tmp_path` 覆盖成功和失败矩阵。 |
| `README.md` | 真实模型一键命令、人工确认、费用、模型覆盖和现场保留说明。 |
| `openspec/changes/add-m22-triad-human-smoke/tasks.md` | 每个任务通过后定向勾选 OpenSpec 实施项。 |

---

### Task 1：以 TDD 建立命令与协作状态验收

**文件：**
- 新建：`scripts/m22-triad-human-smoke.py`
- 新建：`tests/test_m22_triad_human_smoke.py`
- 修改：`openspec/changes/add-m22-triad-human-smoke/tasks.md`

**接口：**
- 产出：`SmokeModels`、`SmokeConfig`、`build_forgeagent_command()`、`load_collaboration_state()`、`collaboration_failures()`。
- 消费：现有 `.venv/bin/forgeagent` 参数契约和 `.forgeagent/collaborations/*.json` 状态格式。

- [x] **Step 1：写入按路径导入、命令组装和成功状态的失败测试**

在测试文件先加入以下骨架与断言；fixture 只写 `tmp_path`：

```python
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_smoke_module():
    path = Path(__file__).parents[1] / "scripts" / "m22-triad-human-smoke.py"
    spec = importlib.util.spec_from_file_location("m22_triad_human_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_state(workdir: Path, **overrides: object) -> Path:
    state: dict[str, object] = {
        "collaboration_id": "a" * 32,
        "mode": "triad",
        "status": "completed",
        "phase": "completed",
        "stop_reason": "completed",
        "plan": [{
            "id": "moving_average",
            "behavior": "Provide moving_average and its CLI.",
            "acceptance": "Files, pytest, and JSON output pass.",
        }],
        "plan_digest": "b" * 64,
        "generator_attempts": 1,
        "evaluator_attempts": 1,
        "rejections": 0,
        "last_evaluation": [{
            "id": "moving_average",
            "passed": True,
            "observed": "All checks pass.",
            "expected": "All checks pass.",
            "location": "calc.py",
        }],
    }
    state.update(overrides)
    directory = workdir / ".forgeagent" / "collaborations"
    directory.mkdir(parents=True, exist_ok=True)
    state_file = directory / f"{'a' * 32}.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def test_build_command_preserves_triad_and_manual_stdio_contract(tmp_path):
    smoke = _load_smoke_module()
    models = smoke.SmokeModels("claude-sonnet-5", "claude-haiku-4-5", "claude-haiku-4-5")
    command = smoke.build_forgeagent_command(tmp_path / "forgeagent", models)
    assert command == [
        str(tmp_path / "forgeagent"), "--model", "claude-sonnet-5",
        "--tier", "restricted", "--no-identity", "--no-memory", "run", "--mode",
        "triad", "--planner-model", "claude-haiku-4-5",
        "--evaluator-model", "claude-haiku-4-5", "--max-rejections",
        "2", smoke.GOAL,
    ]


def test_success_state_has_no_collaboration_failures(tmp_path):
    smoke = _load_smoke_module()
    _write_state(tmp_path)
    state = smoke.load_collaboration_state(tmp_path)
    assert smoke.collaboration_failures(state) == []
```

- [x] **Step 2：运行测试确认 RED**

运行：`uv run pytest tests/test_m22_triad_human_smoke.py -v`

预期：FAIL，原因是 `scripts/m22-triad-human-smoke.py` 尚不存在或接口尚未定义。

- [x] **Step 3：写入状态失败矩阵并再次确认 RED**

增加参数化测试，至少覆盖：零份状态、多份状态、损坏 JSON、`needs_confirmation`、`invalid_role_submission`、空 plan、非法 digest、布尔 attempts、零 attempts、空 evaluation、任一 evaluation `passed is not True`。关键断言如下：

```python
def test_plan_rejection_is_reported_explicitly(tmp_path):
    smoke = _load_smoke_module()
    _write_state(
        tmp_path,
        status="stopped",
        phase="stopped",
        stop_reason="needs_confirmation",
        generator_attempts=0,
        evaluator_attempts=0,
        last_evaluation=[],
    )
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any("needs_confirmation" in item for item in failures)


def test_boolean_attempt_is_not_accepted_as_integer(tmp_path):
    smoke = _load_smoke_module()
    _write_state(tmp_path, generator_attempts=True)
    failures = smoke.collaboration_failures(smoke.load_collaboration_state(tmp_path))
    assert any("generator_attempts" in item for item in failures)


def test_state_discovery_requires_exactly_one_regular_json(tmp_path):
    smoke = _load_smoke_module()
    with pytest.raises(ValueError, match="exactly one collaboration state"):
        smoke.load_collaboration_state(tmp_path)
    _write_state(tmp_path)
    second = tmp_path / ".forgeagent" / "collaborations" / "second.json"
    second.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one collaboration state"):
        smoke.load_collaboration_state(tmp_path)


def test_state_loader_rejects_invalid_json_without_echoing_content(tmp_path):
    smoke = _load_smoke_module()
    secret = "synthetic-state-secret"
    state_file = _write_state(tmp_path)
    state_file.write_text("{" + secret, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid collaboration state JSON") as error:
        smoke.load_collaboration_state(tmp_path)
    assert secret not in str(error.value)
```

运行：`uv run pytest tests/test_m22_triad_human_smoke.py -v`

预期：新增测试继续 FAIL，因为最小实现尚未完成。

- [x] **Step 4：实现最小命令与状态验收**

脚本定义以下精确数据结构和常量；不引入可继承基类：

```python
@dataclass(frozen=True)
class SmokeModels:
    generator: str
    planner: str
    evaluator: str


@dataclass(frozen=True)
class SmokeConfig:
    workdir: Path
    forgeagent: Path
    python: Path
    models: SmokeModels


GOAL = (
    "在当前目录创建 calc.py 和 test_calc.py。calc.py 必须提供 "
    "moving_average(values, window)，window 小于等于 0 或大于数据长度时抛出 "
    "ValueError；命令行执行 python calc.py '[1,2,3,4]' 2 必须输出 JSON "
    "[1.5,2.5,3.5]；使用 pytest 覆盖正常和异常情况。"
)

RunCommand = Callable[..., subprocess.CompletedProcess[str]]
```

相应导入 `Callable`（`collections.abc`）与 `subprocess`；该别名只用于测试注入标注，不包装或改变 `subprocess.run`。

`build_forgeagent_command(forgeagent: Path, models: SmokeModels) -> list[str]` 必须返回设计文档中的固定参数数组；测试有意比较完整 argv，因为参数顺序、缺省开关和固定 goal 都是本冒烟入口的契约。`load_collaboration_state(workdir) -> dict[str, object]` 仅接受恰好一个非 symlink 普通 JSON 文件，使用 `json.loads()` 返回 raw dict；若 JSON root 不是 dict 或文件发现/解析失败，则抛出仅包含稳定原因的 `ValueError`。它不导入 `CollaborationState`，也不要求 fixture 补齐 `schema`、revision、model、usage、rounds 等未消费字段。`collaboration_failures(state)` 自己校验本脚本消费的稳定投影并忽略其他字段：`collaboration_id` 必须匹配 `[0-9a-f]{32}`，plan 必须是非空 list，plan item ID 必须是唯一非空字符串，`plan_digest` 只使用 `[0-9a-f]{64}` 做格式校验而不重算，attempts/rejections 使用 `type(value) is int`，evaluation ID 必须按相同顺序完整覆盖 plan，且 `type(passed) is bool and passed is True`。因此 fixture 中的 `"b" * 64` 是有意的格式样本，不代表真实 plan 哈希。

- [x] **Step 5：运行专项测试与 Ruff 确认 GREEN**

运行：

```bash
uv run pytest tests/test_m22_triad_human_smoke.py -v
uv run ruff check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
uv run ruff format --check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
```

预期：专项测试全部 PASS，Ruff 无诊断、无需格式修改。

- [x] **Step 6：勾选 OpenSpec 1.1 并提交状态验收核心**

Task 1 尚未创建隔离目录或完成完整真实子进程入口，因此只勾选 1.1；跨 Task 1-3 的 1.2 延后到 Task 3 完整交付后勾选：

```bash
rtk node .agents/skills/comet/scripts/comet-state.mjs task-checkoff openspec/changes/add-m22-triad-human-smoke/tasks.md "1.1 以 TDD 增加脚本导入、命令组装、成功状态解析、人工计划拒绝和 ForgeAgent 失败回归"
git add scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py openspec/changes/add-m22-triad-human-smoke/tasks.md
git commit -m "feat: add M22 Triad smoke state checks"
```

### Task 2：以 TDD 增加产物验收与完整运行摘要

**文件：**
- 修改：`scripts/m22-triad-human-smoke.py`
- 修改：`tests/test_m22_triad_human_smoke.py`
- 修改：`openspec/changes/add-m22-triad-human-smoke/tasks.md`

**接口：**
- 消费：Task 1 的 `SmokeConfig`、状态加载和失败列表。
- 产出：`artifact_failures()`、`run_smoke()` 和稳定 PASS/FAIL 摘要。

- [x] **Step 1：写入 fake runner 与产物失败测试**

测试 runner 必须记录 `args`、`cwd` 以及可选的 `capture_output`、`text`，并返回 `subprocess.CompletedProcess`。pytest 调用继承终端输出，所以其 CompletedProcess 的 stdout/stderr 可以是 `None`；只有 CLI 调用要求捕获文本。至少加入：缺 `calc.py`、缺 `test_calc.py`、pytest 非零、CLI stderr 非空、CLI stdout 非 JSON、JSON 值错误。示例：

```python
def test_artifact_check_rejects_wrong_cli_json(tmp_path):
    smoke = _load_smoke_module()
    (tmp_path / "calc.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text("pass\n", encoding="utf-8")
    results = iter([
        smoke.subprocess.CompletedProcess([], 0),
        smoke.subprocess.CompletedProcess([], 0, "[1.5, 2.5]\\n", ""),
    ])

    def run(*args, **kwargs):
        return next(results)

    failures = smoke.artifact_failures(tmp_path, Path("/venv/python"), run)
    assert any("[1.5, 2.5, 3.5]" in item for item in failures)
```

- [x] **Step 2：运行新增测试确认 RED**

运行：`uv run pytest tests/test_m22_triad_human_smoke.py -v`

预期：FAIL，原因是 `artifact_failures()` 尚未定义。

- [x] **Step 3：实现普通文件、pytest 与 CLI JSON 验收**

`artifact_failures(workdir, python, run)` 按顺序：

```python
pytest_result = run([str(python), "-m", "pytest", "-q"], cwd=workdir, check=False)
cli_result = run(
    [str(python), "calc.py", "[1,2,3,4]", "2"],
    cwd=workdir,
    check=False,
    capture_output=True,
    text=True,
)
```

只有两个文件均为非 symlink 普通文件时运行命令；pytest 失败后不运行 CLI。pytest 失败诊断只引用 exit code，不读取或截断其 `stdout`/`stderr`，因此继承 stdio 产生的 `None` 不会触发字符串操作。CLI 要求 `returncode == 0`、`isinstance(stderr, str)`、`stderr.strip() == ""`、`isinstance(stdout, str)` 且 `json.loads(stdout) == [1.5, 2.5, 3.5]`；只有 CLI 的字符串 stdout/stderr 才会在诊断中截断到 200 个字符。

- [x] **Step 4：写入 `run_smoke()` 成功、人工计划拒绝和 ForgeAgent 非零测试**

成功 fake runner 的第一次调用在 `cwd` 下写入单份成功状态、`calc.py` 和 `test_calc.py`；后两次分别模拟 pytest 与 CLI。断言：

```python
assert smoke.run_smoke(config, run=fake_run) == 0
output = capsys.readouterr().out
assert "M22 TRIAD HUMAN SMOKE: PASS" in output
assert f"workdir: {config.workdir}" in output
assert "collaboration: " + "a" * 32 in output
assert "generator_attempts: 1" in output
assert "evaluator_attempts: 1" in output
```

失败测试断言 exit 1、`FAIL`、workdir 总会打印。合成 secret 通过 `_write_state()` overrides 放入 `plan[0].behavior`、`last_evaluation[0].observed` 和额外 `api_key` 字段，再断言 stdout/stderr 均不包含该字符串；这验证的是 raw state 到稳定诊断投影，不要求 `run_smoke()` 扫描或隐藏真实环境变量：

```python
def test_failure_summary_does_not_echo_untrusted_state_fields(tmp_path, capsys):
    smoke = _load_smoke_module()
    secret = "synthetic-state-secret"
    config = _config(smoke, tmp_path)

    def failed_forgeagent(*args, **kwargs):
        _write_state(
            tmp_path,
            status="failed",
            phase="failed",
            stop_reason="invalid_role_submission",
            plan=[{
                "id": "moving_average",
                "behavior": secret,
                "acceptance": "Files pass.",
            }],
            last_evaluation=[{
                "id": "moving_average",
                "passed": False,
                "observed": secret,
                "expected": "Submit through the role tool.",
                "location": "calc.py",
            }],
            api_key=secret,
        )
        return smoke.subprocess.CompletedProcess(args[0], 1)

    assert smoke.run_smoke(config, run=failed_forgeagent) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "invalid_role_submission" in captured.out + captured.err
```

ForgeAgent 调用必须使用继承 stdio：调用 kwargs 只能包含 `cwd=config.workdir` 和 `check=False`，不得含 `input`、`capture_output`、`stdin`、`stdout` 或 `stderr`。

- [x] **Step 5：实现 `run_smoke()` 最小控制流并确认 GREEN**

实现顺序固定为：打印 workdir → 运行 ForgeAgent → 尝试加载状态 → 若进程非零或状态失败则打印有界失败 → 状态成功才验收产物 → 打印摘要。捕获 `KeyboardInterrupt` 并返回 130；不捕获 `BaseException`，不删除工作目录。

运行：

```bash
uv run pytest tests/test_m22_triad_human_smoke.py -v
uv run ruff check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
uv run ruff format --check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
```

预期：全部 PASS。

- [x] **Step 6：勾选 OpenSpec 2.1 和 2.2 并提交**

```bash
rtk node .agents/skills/comet/scripts/comet-state.mjs task-checkoff openspec/changes/add-m22-triad-human-smoke/tasks.md "2.1 以 TDD 增加缺文件、pytest 失败和 CLI JSON 不匹配回归"
rtk node .agents/skills/comet/scripts/comet-state.mjs task-checkoff openspec/changes/add-m22-triad-human-smoke/tasks.md "2.2 实现文件、pytest 与 moving-average CLI 输出验收，并打印最终摘要"
git add scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py openspec/changes/add-m22-triad-human-smoke/tasks.md
git commit -m "test: validate M22 Triad smoke artifacts"
```

### Task 3：以 TDD 完成交互预检、模型覆盖和一键入口

**文件：**
- 修改：`scripts/m22-triad-human-smoke.py`
- 修改：`tests/test_m22_triad_human_smoke.py`

**接口：**
- 消费：Task 1/2 的 `SmokeModels`、`SmokeConfig` 和 `run_smoke()`。
- 产出：`models_from_environment()`、`main() -> int` 与脚本 `__main__` 入口。

- [ ] **Step 1：写入非 TTY、非法模型和缺可执行文件的失败测试**

`test_main_rejects_non_tty_before_creating_workdir` 同时 monkeypatch `tempfile.mkdtemp` 为一旦调用就抛错，证明非 TTY 在目录创建前结束。另加环境变量值 `""`、包含 `\n`、长度 501，以及缺 `.venv/bin/forgeagent`/`.venv/bin/python` 测试。非 TTY 断言：

```python
monkeypatch.setattr(smoke.sys.stdin, "isatty", lambda: False)
monkeypatch.setattr(smoke.sys.stdout, "isatty", lambda: True)
monkeypatch.setattr(smoke.tempfile, "mkdtemp", lambda **kwargs: pytest.fail("created workdir"))
assert smoke.main() == 2
assert "interactive terminal" in capsys.readouterr().err
```

- [ ] **Step 2：运行入口测试确认 RED**

运行：`uv run pytest tests/test_m22_triad_human_smoke.py -v`

预期：FAIL，原因是 `main()` 或环境预检尚未实现。

- [ ] **Step 3：实现模型读取和入口预检**

默认值固定为设计值。`_valid_model_id(value)` 要求 `0 < len(value) <= 500` 且 `unicodedata.category(character)` 不以 `C` 开头；环境变量已存在但为空时不得回退默认值。`main()` 顺序必须是：TTY → 模型 → 两个 executable 的 `is_file()` 与 `os.access(path, os.X_OK)` → `mkdtemp(prefix="forgeagent-m22-human-", dir="/tmp")` → `SmokeConfig` → `run_smoke()`。虚拟环境 executable 允许是 symlink；状态 JSON 和生成产物仍拒绝 symlink。

入口只做：

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

不增加 argparse 或命令行选项。

- [ ] **Step 4：写入交互成功入口测试并确认 GREEN**

monkeypatch 两个 TTY 为真、三个模型环境变量、`Path` 检查与 `mkdtemp`，将 `run_smoke` 替换为记录 config 的 stub。断言 env 覆盖准确传入、workdir 前缀为 `forgeagent-m22-human-`、返回值透传。

运行：

```bash
uv run pytest tests/test_m22_triad_human_smoke.py -v
uv run ruff check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
uv run ruff format --check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
```

预期：全部 PASS；测试调用记录中没有真实 `.venv/bin/forgeagent` 进程。

- [ ] **Step 5：勾选跨任务 OpenSpec 1.2 并提交完整交互入口**

```bash
rtk node .agents/skills/comet/scripts/comet-state.mjs task-checkoff openspec/changes/add-m22-triad-human-smoke/tasks.md "1.2 实现隔离目录、真实 Triad 子进程、状态读取与稳定诊断"
git add scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py openspec/changes/add-m22-triad-human-smoke/tasks.md
git commit -m "feat: add interactive M22 Triad smoke entry"
```

### Task 4：文档、严格验证和最终代码审查

**文件：**
- 修改：`README.md`
- 修改：`openspec/changes/add-m22-triad-human-smoke/tasks.md`
- 验证：`scripts/m22-triad-human-smoke.py`
- 验证：`tests/test_m22_triad_human_smoke.py`

**接口：**
- 消费：前 3 个任务完成的一键入口。
- 产出：用户可直接运行的说明、完整验证证据和全部已勾选任务。

- [ ] **Step 1：更新 README 的 M22 人类冒烟说明**

在现有 M22 Duo/Triad 文档附近加入：

````markdown
### M22 真实模型 Triad 人类冒烟

以下命令会调用真实模型并可能产生费用；必须在交互式终端运行。请在 Planner
显示计划后人工选择是否批准，restricted tier 的其他确认也会保持原样：

```bash
uv run --offline python scripts/m22-triad-human-smoke.py
```

可通过 `FORGEAGENT_M22_MODEL`、`FORGEAGENT_M22_PLANNER_MODEL` 和
`FORGEAGENT_M22_EVALUATOR_MODEL` 覆盖 Generator、Planner 和 Evaluator 模型。
脚本会自动检查协作终态、生成文件、pytest 与 CLI JSON；无论成功或失败，现场目录都会
保留在 `/tmp/forgeagent-m22-human-*`。这是人工验收冒烟测试，不是 benchmark 或 CI gate。
````

调整围栏嵌套使 Markdown 合法；不要记录 API key 示例或自动批准命令。

- [ ] **Step 2：运行专项、非 TTY 黑盒和 Ruff**

```bash
uv run pytest tests/test_m22_triad_human_smoke.py -v
uv run --offline python scripts/m22-triad-human-smoke.py </dev/null
uv run ruff check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
uv run ruff format --check scripts/m22-triad-human-smoke.py tests/test_m22_triad_human_smoke.py
```

预期：pytest 全部 PASS；非 TTY 黑盒以 2 退出并且不创建新 `/tmp/forgeagent-m22-human-*`；Ruff 全部通过。不要在自动验证中执行交互式真实模型路径。

- [ ] **Step 3：运行 OpenSpec、格式和完整 pytest**

```bash
openspec validate add-m22-triad-human-smoke --strict
git diff --check
uv run pytest -q
```

预期：OpenSpec valid、diff 无 whitespace error、完整测试全部通过。

- [ ] **Step 4：按所选 review_mode 完成独立代码审查并修复阻塞项**

若 `review_mode=standard`，使用 `requesting-code-review` 对 `base-ref..HEAD` 加未提交 diff 做一次正确性、安全、边界轻量审查。Critical/Important 必须修复并重新运行 Step 2/3；接受非阻塞发现时，在提交正文或验证报告记录理由。

- [ ] **Step 5：勾选 OpenSpec 3.1 和 3.2，确认计划与 OpenSpec 均无未完成项**

```bash
rtk node .agents/skills/comet/scripts/comet-state.mjs task-checkoff openspec/changes/add-m22-triad-human-smoke/tasks.md "3.1 更新 README 一键命令、人工确认、模型覆盖、费用和现场保留说明"
rtk node .agents/skills/comet/scripts/comet-state.mjs task-checkoff openspec/changes/add-m22-triad-human-smoke/tasks.md "3.2 运行专项、ruff、OpenSpec strict 与完整 pytest，并完成独立代码复审"
rg -n '\- \[ \]' openspec/changes/add-m22-triad-human-smoke/tasks.md docs/superpowers/plans/2026-07-26-m22-triad-human-smoke.md
```

预期：`rg` 无输出。只有验证通过后才能勾选当前计划的最后步骤。

- [ ] **Step 6：提交文档和最终验证状态**

```bash
git add README.md openspec/changes/add-m22-triad-human-smoke/tasks.md docs/superpowers/plans/2026-07-26-m22-triad-human-smoke.md
git commit -m "docs: add M22 Triad human smoke guide"
```

提交后再次运行 `git status --short`，确认仅保留实施前已有的无关未跟踪文件。

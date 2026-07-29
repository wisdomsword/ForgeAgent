---
change: m28-v0-1-release-candidate
design-doc: docs/superpowers/specs/2026-07-29-m28-v0-1-release-candidate-design.md
base-ref: 49e0c05efba0bdbaf20387aee6bbbc77dfe568cd
---

# M28 v0.1 Release Candidate 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从真实 `forgeagent-0.1.0` wheel 建立一条离线、确定、可在 Linux Docker CI 复现的 CLI/HTTP/Single/Duo/Triad RC 门禁，并冻结发布说明与已知限制。

**Architecture:** 单一 `scripts/m28_release_candidate_smoke.py` 采用父/子模式：父模式校验 wheel、创建 Python 3.11 venv、安装并以 `-I` 启动子模式；子模式证明安装来源并通过真实 console script、loopback HTTP 和 `MockClient` 驱动的真实协作运行时完成六项检查。版本化 JSON 是本地测试与 GitLab Linux job 共用的证据边界；发布口径集中在一份 RC 文档。

**Tech Stack:** Python 3.11+、标准库 `argparse/hashlib/importlib.metadata/json/subprocess/tempfile/urllib/venv/zipfile`、现有 ForgeAgent runtime、pytest、uv、GitLab CI、Docker 29.2.1、OpenSpec/Comet、Ruff。

## Global Constraints

- OpenSpec delta spec 是行为合同事实源，Design Doc 是实现细节事实源。
- 候选版本固定为 `0.1.0`，clean-wheel 解释器固定验证最低支持版本 Python 3.11。
- 不新增运行时依赖、产品 CLI 子命令、provider 请求、credential 读取、模型路由或 sandbox 行为。
- CLI 必须执行 venv 中安装生成的 `forgeagent` console script；HTTP 必须走 `127.0.0.1:0` 真实请求；协作必须显式执行 Single、Duo、Triad。
- 报告 schema 固定为 `forgeagent.release-candidate-smoke/v1`，必需检查名固定为 `clean-wheel`、`cli`、`http`、`single`、`duo`、`triad`。
- 报告状态只允许 `passed`、`failed`、`not-run`；只有六项全部 `passed` 时顶层 `passed` 才为 true，skip/not-run 不得算成功。
- 报告不得包含环境变量值、credential、目标正文、模型回复、绝对临时路径、文件内容或原始 exception/stdout/stderr。
- Linux Docker job 保留现有 10 项 container integration 的 tests=10、failures=errors=skipped=0 精确门禁，并额外发布 RC JSON。
- M24 Pipeline 50 / Job 249 只能作为历史 container 证据，不能冒充 M28 installed-wheel smoke 通过。
- 保留并不提交用户已有未跟踪文件；不修改 M23/M25 冻结输入。

---

### Task 1: RC harness 合同与离线入口

**Files:**
- Create: `scripts/m28_release_candidate_smoke.py`
- Create: `tests/test_m28_release_candidate_smoke.py`

**Interfaces:**
- Consumes: wheel path、output path、Python executable；现有 `MockClient`、`Task`、`HttpServiceConfig`、`TaskService`、`create_http_server`、`CollaborationRunner.create()`。
- Produces: `SCHEMA = "forgeagent.release-candidate-smoke/v1"`、`CHECK_NAMES = ("clean-wheel", "cli", "http", "single", "duo", "triad")`；`clean_environment(source, home) -> dict[str, str]`；`wheel_identity(path) -> tuple[str, str]`；`write_report(path, report) -> None`；`run_parent(wheel, output, python) -> int`；`run_installed(output, wheel_sha256) -> int`；CLI `--wheel/--output/--python` 与私有 `--installed`。

- [x] **Step 1: 写 metadata、环境与报告 RED 合同**

按路径导入尚不存在的脚本，写入以下确定合同：

```python
def test_clean_environment_removes_import_and_provider_secrets(tmp_path):
    cleaned = smoke.clean_environment(
        {
            "PATH": "/usr/bin",
            "PYTHONHOME": "/source/python",
            "PYTHONPATH": "/source/src",
            "ANTHROPIC_API_KEY": "secret",
            "OPENAI_API_KEY": "secret",
            "LLM_API_KEY": "secret",
            "SAFE_FLAG": "kept",
        },
        tmp_path,
    )
    assert cleaned["HOME"] == str(tmp_path)
    assert cleaned["SAFE_FLAG"] == "kept"
    assert not ({"PYTHONHOME", "PYTHONPATH", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"} & cleaned.keys())

def test_write_report_is_complete_and_bounded(tmp_path):
    report = smoke.new_report("a" * 64)
    report["checks"] = dict.fromkeys(smoke.CHECK_NAMES, "passed")
    smoke.finalize_report(report)
    output = tmp_path / "report.json"
    smoke.write_report(output, report)
    loaded = json.loads(output.read_text())
    assert loaded["schema"] == "forgeagent.release-candidate-smoke/v1"
    assert loaded["version"] == "0.1.0"
    assert loaded["passed"] is True
    assert set(loaded["checks"]) == set(smoke.CHECK_NAMES)
    assert "secret" not in output.read_text()
```

用最小 synthetic wheel ZIP 覆盖正确 `Name: forgeagent`/`Version: 0.1.0`、错误 name/version、非普通文件和 SHA-256 小写 64 hex。用 monkeypatch 让 `os.replace` 记录源/目标并断言同目录临时文件先 flush/fsync 后替换。

- [x] **Step 2: 运行基础合同确认 RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py -k 'environment or report or wheel'`

Expected: FAIL，因为 `scripts/m28_release_candidate_smoke.py` 不存在。

- [x] **Step 3: 实现最小 metadata、环境与报告核心**

实现固定常量与纯函数。`wheel_identity()` 用 `zipfile.ZipFile` 找唯一 `.dist-info/METADATA`，用 `email.parser.Parser` 读取 Name/Version，拒绝多份或不匹配。`clean_environment()` 复制 allowlisted 普通环境但移除 `PYTHONHOME/PYTHONPATH` 及 `is_secret_name(name)` 命中的 key，设置临时 `HOME`。报告初态六项全 `not-run`；`finalize_report()` 只从六项状态计算 `passed`；`write_report()` 在 output 父目录用 `NamedTemporaryFile(delete=False)` 写 `sort_keys=True` JSON + 换行、flush/fsync 后 `os.replace()`，失败时删除临时文件。

- [x] **Step 4: 写 CLI/HTTP/Single/Duo/Triad RED 合同**

增加五组真实入口测试：

```python
def test_cli_check_uses_console_script_and_builtin_models(tmp_path):
    # 传当前等价 console path；断言 --help 与 models 都返回 0，且稳定标识存在。
    smoke.check_cli(Path(sys.executable).parent / "forgeagent", smoke.clean_environment(os.environ, tmp_path))

def test_http_check_uses_real_loopback_and_closes():
    smoke.check_http()

@pytest.mark.parametrize("mode", ["single", "duo", "triad"])
def test_collaboration_checks_complete_without_provider(mode, tmp_path):
    report = smoke.check_collaboration(mode, tmp_path)
    assert report == {"mode": mode, "status": "completed"}
```

HTTP 测试必须真实分配 socket；无 token `POST /tasks` 断言 401 且无 record；有 token提交后 GET，再 `POST /tasks/<id>/cancel`，最终状态 cancelled；退出后 server thread 不存活。协作固定 ToolCall JSON：Planner `SubmitPlan` 输入包含一项 `{id, behavior, acceptance}`；Generator `SubmitCandidate` 输入 `{}`；Evaluator `SubmitEvaluation` 输入包含相同 id 的 `{passed: true, observed: "observed", expected: "expected", location: "runtime"}`。Single 使用现有完成 marker。字段以当前 Pydantic 协议契约为准，不为 smoke 扩展产品接口。

- [x] **Step 5: 运行入口合同确认 RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py -k 'cli or http or collaboration'`

Expected: FAIL，因为入口检查函数尚未实现。

- [x] **Step 6: 实现最小入口与父/子流程**

实现：

- CLI：`subprocess.run([console, "--help"], shell=False, timeout=30)` 和 `[console, "models"]`，只匹配 `Lightweight code-as-action agent`、`run`、`serve`、`claude-sonnet-5`。
- HTTP：本地 `ControlledTask.run()` 循环等待 cancel event，返回稳定 `TaskOutcome`；真实 server thread + `urllib.request`；`finally` 关闭 server/service/thread。
- Single：`Task(MockClient([completed_reply])).run(goal)`。
- Duo/Triad：每个 role builder 创建真实 `Task(MockClient(script), tool_registry=registry, system_prompt=prompt)`；`CollaborationRunner.create(..., execution_tier="restricted")`；Triad confirmer 固定 true；断言 report mode/status/count。
- 子模式：证明 `importlib.metadata.version("forgeagent") == "0.1.0"`，`forgeagent.__file__` 与 console script 在 `sys.prefix` 内，读取包内 models YAML 与 prompt；按顺序更新六项检查。
- 父模式：校验 wheel，`python -m venv`，venv `python -m pip install <wheel>`，从临时 probe cwd 以 `[venv_python, "-I", script, "--installed", ...]` 运行子模式；每个 subprocess 有 180 秒 timeout 且 `shell=False`。

任何失败只把当前项设为 `failed`，其后仍未运行项保持 `not-run`，写报告并返回 1；stderr 只输出 `M28 RC smoke failed: <fixed-check-name>`。

- [x] **Step 7: 运行 GREEN、相邻回归并提交**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py tests/test_http_server.py tests/test_http_task_service.py tests/test_collaboration_runner.py`

Expected: 全部 PASS。

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py && UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py`

Expected: 两项 PASS。

```bash
git add scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
git commit -m "feat: add installed-wheel release candidate smoke"
```

### Task 2: 真实 wheel packaging 与 Linux Docker 门禁

**Files:**
- Modify: `tests/test_packaging.py`
- Modify: `.gitlab-ci.yml`
- Create: `tests/test_m28_release_ci.py`

**Interfaces:**
- Consumes: Task 1 CLI `python scripts/m28_release_candidate_smoke.py --wheel PATH --output PATH --python PATH` 和固定 JSON schema/check names。
- Produces: packaging 真实 wheel smoke；GitLab artifact `artifacts/ci/rc-smoke.json`；结构化 CI 合同测试。

- [x] **Step 1: 写 packaging/CI RED 合同**

把 `test_wheel_and_sdist_release_contents()` 的现有 sdist allowlist 保持不变，新增调用记录或真实调用断言，要求其最终运行：

```python
subprocess.run(
    [sys.executable, str(repo_root / "scripts/m28_release_candidate_smoke.py"),
     "--wheel", str(wheels[0]), "--output", str(report), "--python", sys.executable],
    cwd=probe_dir,
    check=True,
    env=_clean_python_environment(uv_env),
)
assert json.loads(report.read_text())["passed"] is True
```

新建 `tests/test_m28_release_ci.py`，用 PyYAML 读取 `.gitlab-ci.yml`，要求 `linux-docker-container` script 同时包含 `uv build --wheel`、M28 harness、`python:3.11-slim`、JSON 六项校验；artifact paths 同时包含 `container-junit.xml` 和 `rc-smoke.json`；旧 `tests == 10`/`skipped == 0` 原样保留，且 job 无 `allow_failure: true`。

- [x] **Step 2: 运行合同确认 RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_ci.py tests/test_packaging.py -k 'release_ci or wheel_and_sdist'`

Expected: FAIL，因为 GitLab job 尚未调用 RC harness，packaging 仍使用旧手写 probe。

- [x] **Step 3: 复用 harness 完成 packaging GREEN**

在 `tests/test_packaging.py` 导入 `json`、`sys`，删除重复的 venv/install/`-c` probe 块，改为从非仓库 `probe_dir` 调用 Task 1 的唯一 harness。保留 `_clean_python_environment()`、全部 sdist allowed/forbidden 路径和 prompt suffix 断言。断言报告 schema、passed 和六项状态；不得从 `tests/` 注入 wheel 环境。

- [x] **Step 4: 接入 Linux Docker job**

在既有 10 项 JUnit 断言后：

1. `su-exec forgeagent uv build --wheel --out-dir artifacts/ci/dist`。
2. 断言恰有一个 `forgeagent-0.1.0-*.whl`。
3. 以固定 `python:3.11-slim` 启动一次性容器，挂载同路径项目卷、`--user 1000:1000`、项目内 `HOME/TMPDIR`，从非仓库工作目录执行 `python scripts/m28_release_candidate_smoke.py --wheel ... --output artifacts/ci/rc-smoke.json --python python`；不传 credential，不使用 editable install。
4. 标准库 one-liner 读取 JSON，要求 schema 精确匹配、`passed is True`、六项集合和值全为 `passed`。
5. artifact paths 增加 `artifacts/ci/rc-smoke.json`，`when: always` 保持不变。

不要删除 DinD、`docker-privileged`、non-root `su-exec`、`TMPDIR` same-path、image preflight 或 JUnit 精确门禁。

- [x] **Step 5: 运行 GREEN 与真实 wheel smoke并提交**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_ci.py tests/test_packaging.py`

Expected: 全部 PASS，真实 wheel JSON 六项 passed。

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check tests/test_packaging.py tests/test_m28_release_ci.py && UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check tests/test_packaging.py tests/test_m28_release_ci.py`

Expected: 两项 PASS。

```bash
git add tests/test_packaging.py tests/test_m28_release_ci.py .gitlab-ci.yml
git commit -m "ci: gate Linux releases on installed-wheel smoke"
```

### Task 3: RC 发布说明与限制合同

**Files:**
- Create: `docs/releases/0.1.0-rc.md`
- Modify: `README.md`
- Modify: `docs/platform-support.md`
- Create: `tests/test_m28_release_docs.py`

**Interfaces:**
- Consumes: 实际已运行验证结果、M24 历史 Linux container 证据、Task 2 configured M28 gate。
- Produces: 单一 RC 发布入口和静态合同，明确 configured/verified/opt-in/known limitation 边界。

- [x] **Step 1: 写发布文档 RED 合同**

新增测试要求 RC 文档存在并包含唯一一级标题、`0.1.0`、wheel 安装命令、CLI/HTTP/Single/Duo/Triad、正式发布阻塞条件，以及五个固定已知限制标题：平台证据、真实模型、sandbox、HTTP、协作 v1。要求出现 `restricted 不是 OS 级密封沙箱`、loopback/default bind 边界、headless Triad 计划策略、真实 provider opt-in。要求不出现 `M28 Linux RC smoke 已通过`，除非同文档有真实 pipeline/job id 或本机 Linux Docker 命令证据。

README 必须在“当前验证”附近链接 `docs/releases/0.1.0-rc.md` 并写“Release Candidate，不是正式发布”。平台文档必须把 M24 Job 249 标为 historical container-only evidence，并把 M28 installed-wheel gate 标为 configured 或附新证据，二者不得混写。

- [x] **Step 2: 运行文档合同确认 RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_docs.py`

Expected: FAIL，因为 RC 发布说明与 README/platform 更新不存在。

- [x] **Step 3: 写最小发布说明与公开链接**

创建 `docs/releases/0.1.0-rc.md`，章节固定为：状态、安装、已交付能力、验证证据、正式发布阻塞条件、已知限制。验证表把已实际完成的本机 clean-wheel/专项写为 verified；M28 required Linux job 在未运行前写 configured/pending，不得复用 Job 249。已知限制完整解释五类边界，不复制整份 README。

README 只增加 1 个短 RC 段落和链接；`docs/platform-support.md` 增加 M28 gate 的 configured 状态、所需 `rc-smoke.json` 证据和下一触发条件，保留所有 M24 历史记录。

- [x] **Step 4: 运行 GREEN、相邻文档合同并提交**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_docs.py tests/test_collaboration_docs.py tests/test_continuous_verification.py`

Expected: 全部 PASS。

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check tests/test_m28_release_docs.py && UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check tests/test_m28_release_docs.py`

Expected: 两项 PASS。

```bash
git add docs/releases/0.1.0-rc.md README.md docs/platform-support.md tests/test_m28_release_docs.py
git commit -m "docs: freeze ForgeAgent 0.1 release candidate"
```

### Task 4: 全量验证、证据定稿与 M28 里程碑

**Files:**
- Create: `docs/superpowers/reports/2026-07-29-m28-v0-1-release-candidate-verify.md`
- Create: `milestones/milestone_028.md`
- Modify: `milestones/latest`
- Modify: `ACTION_PLAN.md`
- Modify: `README.md`
- Modify: `docs/platform-support.md`
- Modify: `docs/releases/0.1.0-rc.md`
- Modify: `openspec/changes/m28-v0-1-release-candidate/tasks.md`

**Interfaces:**
- Consumes: Tasks 1-3 实现、RC JSON、测试/build/OpenSpec/Docker 原始输出。
- Produces: 只陈述实际执行结果的验证报告、公开基线与 M28 续接指引。

- [x] **Step 1: 运行分层验证并保存原始结论**

依次运行，任一意外失败先按 systematic-debugging 根因调查，不得先改文档：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py tests/test_m28_release_ci.py tests/test_m28_release_docs.py tests/test_packaging.py
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run python -m tests.golden.runner --output-dir artifacts/m28/golden
rtk openspec validate --all --strict
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv build --out-dir artifacts/m28/dist
```

构建后从 `artifacts/m28/dist` 取唯一 wheel，再运行：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run python scripts/m28_release_candidate_smoke.py \
  --wheel artifacts/m28/dist/forgeagent-0.1.0-*.whl \
  --output artifacts/m28/rc-smoke.json --python python3.11
```

若 Docker 可用，运行现有十项：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_container_backend.py \
  -m container_integration --junitxml=artifacts/m28/container-junit.xml
```

再在 `python:3.11-slim` Linux 容器内运行同一 wheel smoke并输出独立 `artifacts/m28/linux-rc-smoke.json`。若本机环境不能运行某项，记录固定阻塞原因和未验证，不得写 pass。

- [x] **Step 2: 用实际数字定稿公开证据**

从命令输出和 JSON/JUnit 读取实际计数，不手抄预期值。更新 README 当前验证、平台矩阵和 RC 文档：full pytest、skip/fail、OpenSpec N/N、Golden 20/20、clean-wheel 六项、Docker 10 项、Linux RC smoke。没有真实 required GitLab pipeline 时，M28 CI 仍写 configured；本机 Linux container 只写 supplemental local evidence。

- [x] **Step 3: 生成验证报告与 milestone，准备归档输入**

验证报告包含：scope、逐命令结果、RC JSON 字段摘要、代码审查发现/修复、环境限制、已知限制、OpenSpec scenario 映射。`milestone_028.md` 按 `MILESTONE_GUIDE.md` 包含范围、提交、实证、未验证项和续接指引；ACTION_PLAN 新增 M28 行并只使用实际结果。build 阶段准备完整归档输入；`milestones/latest` 只在 Comet archive 成功后写 `milestone_028.md`，不得提前移动权威续接指针。

- [x] **Step 4: 复跑文档/strict 合同并提交**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_docs.py tests/test_continuous_verification.py tests/test_collaboration_docs.py`

Expected: 全部 PASS。

Run: `rtk openspec validate --all --strict`

Expected: 所有 specs PASS。

```bash
git add README.md ACTION_PLAN.md docs/platform-support.md docs/releases/0.1.0-rc.md \
  docs/superpowers/reports/2026-07-29-m28-v0-1-release-candidate-verify.md \
  milestones/milestone_028.md milestones/latest \
  openspec/changes/m28-v0-1-release-candidate/tasks.md
git commit -m "chore: close M28 release candidate milestone"
```

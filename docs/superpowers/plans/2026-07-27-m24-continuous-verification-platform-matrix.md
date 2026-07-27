---
change: m24-continuous-verification-platform-matrix
design-doc: docs/superpowers/specs/2026-07-27-m24-continuous-verification-platform-matrix-design.md
base-ref: 2aaeec33ec797be73f1f91b2a8bf0ea9a7c61906
---

# M24 持续验证与平台矩阵 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 ForgeAgent 建立必需的 GitLab 离线验证和 Linux Docker container 门，并以证据驱动的平台矩阵约束发布支持声明。

**Architecture:** 使用两个直接 GitLab CI jobs：基础 job 运行仓库全部离线门并发布 Golden/dist artifacts，Docker job 在固定 DinD 环境通过专用 pytest marker 和 JUnit XML 证明 10 项真实测试零 skip。离线合同测试结构化检查 CI YAML、marker 数量、平台状态和公开文档，不新增产品运行时代码。

**Tech Stack:** GitLab CI YAML、Node 22、Python 3.11、uv 0.11.1、pytest/PyYAML、Ruff、OpenSpec 1.4.1、Docker CLI/DinD 29.2.1、JUnit XML、Markdown。

## Global Constraints

- OpenSpec `continuous-verification` delta 是行为合同事实源，Design Doc 是实现细节事实源。
- 不修改 `src/forgeagent/`、产品依赖、credential、模型路由或 sandbox 行为。
- `offline-verification` 和 `linux-docker-container` 都是 required job，不得设置 `allow_failure: true`。
- Docker job 必须在 pytest 前验证 daemon 和 `python:3.11-slim`，并在 pytest 后验证 tests=10、failures=errors=skipped=0。
- Docker job 必须使用 `docker-privileged` runner，并将 `TMPDIR` 放在 `$CI_PROJECT_DIR` 下以满足 job/DinD 共享 build volume 的 same-path mount 合同。
- 保留现有 `docker_required` skipif；普通离线 pytest 可 skip 10 项，Docker job 不可。
- Linux Docker 无目标 runner 证据时只能标为 `configured`；本机 macOS Docker 只能标为 `supplemental`。
- Podman 与 Windows 本期只排期，不实现兼容代码或声明支持。
- 保留用户未跟踪文件和 M23 未纳入证据的本地尝试目录，不得暂存或修改。

---

### Task 1: CI 与 marker 失败合同

**Files:**
- Create: `tests/test_continuous_verification.py`
- Test: `tests/test_continuous_verification.py`

**Interfaces:**
- Consumes: future `.gitlab-ci.yml`, `pyproject.toml`, `tests.test_container_backend`, `docs/platform-support.md`, README/ACTION_PLAN/milestone paths.
- Produces: structural CI/document contracts used by every later task.

- [x] **Step 1: Write failing CI structure tests**

Create helpers that load YAML and normalize job script lines:

```python
from pathlib import Path
import inspect
import yaml

ROOT = Path(__file__).resolve().parents[1]

def _ci() -> dict:
    return yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))

def _script(job: dict) -> str:
    return "\n".join(job.get("before_script", []) + job.get("script", []))
```

Add tests asserting:

```python
def test_required_ci_jobs_cover_all_gates():
    ci = _ci()
    offline = ci["offline-verification"]
    docker = ci["linux-docker-container"]
    assert offline["stage"] == docker["stage"] == "verify"
    assert offline.get("allow_failure") is not True
    assert docker.get("allow_failure") is not True
    offline_script = _script(offline)
    for expected in (
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run pytest -q",
        "tests.golden.runner",
        "openspec validate --all --strict",
        "uv build --out-dir dist",
    ):
        assert expected in offline_script

def test_docker_job_requires_preflight_and_zero_skip_junit():
    docker = _ci()["linux-docker-container"]
    script = _script(docker)
    assert docker["image"] == "docker:29.2.1-cli"
    assert docker["services"][0]["name"] == "docker:29.2.1-dind"
    for expected in (
        "docker info",
        "docker pull python:3.11-slim",
        "docker image inspect python:3.11-slim",
        "-m container_integration",
        "--junitxml=artifacts/ci/container-junit.xml",
        "tests == 10",
        "skipped == 0",
    ):
        assert expected in script
```

- [x] **Step 2: Write failing marker and documentation tests**

Reflect module test functions and count markers:

```python
def test_container_module_has_four_unit_and_ten_integration_tests():
    from tests import test_container_backend

    tests = [
        value
        for name, value in vars(test_container_backend).items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    marked = [
        test
        for test in tests
        if any(mark.name == "container_integration" for mark in getattr(test, "pytestmark", []))
    ]
    assert len(tests) == 14
    assert len(marked) == 10
```

Add document assertions for `docs/platform-support.md`, the five explicit statuses/terms, and README/ACTION_PLAN/milestone links.

- [x] **Step 3: Run the new test file and observe RED**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q tests/test_continuous_verification.py`

Expected: FAIL because `.gitlab-ci.yml`, marker registration, platform document and M24 public docs do not exist.

- [x] **Step 4: Commit the RED contract**

```bash
git add tests/test_continuous_verification.py
git commit -m "test: define M24 continuous verification contracts"
```

### Task 2: Container integration marker

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_container_backend.py`
- Test: `tests/test_continuous_verification.py`

**Interfaces:**
- Consumes: pytest marker name `container_integration` from Task 1.
- Produces: stable selection of exactly 10 real Docker tests.

- [x] **Step 1: Register the marker**

Extend `[tool.pytest.ini_options]`:

```toml
markers = [
    "container_integration: requires a real container daemon and worker image",
]
```

- [x] **Step 2: Apply marker to the ten real Docker tests**

Define next to `docker_required`:

```python
container_integration = pytest.mark.container_integration
```

Add `@container_integration` to each of the ten tests already decorated with `@docker_required`; do not mark the four no-Docker unit tests.

- [x] **Step 3: Run marker contract and collection checks**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q tests/test_continuous_verification.py::test_container_module_has_four_unit_and_ten_integration_tests`

Expected: PASS.

Run: `UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest --collect-only -q tests/test_container_backend.py -m container_integration`

Expected: output ends with `10/14 tests collected (4 deselected)` or equivalent pytest collection summary.

- [x] **Step 4: Commit marker implementation**

```bash
git add pyproject.toml tests/test_container_backend.py tests/test_continuous_verification.py
git commit -m "test: mark real container integration cases"
```

### Task 3: GitLab offline verification job

**Files:**
- Create: `.gitlab-ci.yml`
- Test: `tests/test_continuous_verification.py`

**Interfaces:**
- Consumes: repository uv/OpenSpec/Ruff/pytest/Golden/build commands.
- Produces: required `offline-verification` job and Golden/dist artifacts.

- [x] **Step 1: Add global workflow, variables, cache, and verify stage**

Create `.gitlab-ci.yml` with:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH

stages:
  - verify

variables:
  GIT_DEPTH: "0"
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.cache/uv"

cache:
  key: "uv-$CI_COMMIT_REF_SLUG"
  paths:
    - .cache/uv
```

- [x] **Step 2: Add the pinned offline job**

Use `node:22.22.0-bookworm-slim`, install Debian Python 3.11, pip, venv, git and CA certificates, install `uv==0.11.1` and `@fission-ai/openspec@1.4.1`, then run the six commands from the design. Configure `artifacts:when: always` for `artifacts/ci/golden/` and `dist/`.

- [x] **Step 3: Run structural contract**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q tests/test_continuous_verification.py::test_required_ci_jobs_cover_all_gates`

Expected: the offline assertions pass; Docker assertions may remain RED until Task 4.

- [x] **Step 4: Commit offline CI**

```bash
git add .gitlab-ci.yml tests/test_continuous_verification.py
git commit -m "ci: add required offline verification gate"
```

### Task 4: Linux Docker required job

**Files:**
- Modify: `.gitlab-ci.yml`
- Test: `tests/test_continuous_verification.py`

**Interfaces:**
- Consumes: marker from Task 2 and fixed Docker/image identifiers.
- Produces: DinD job, JUnit artifact and tests=10/skipped=0 enforcement.

- [x] **Step 1: Add Docker CLI/DinD service and variables**

Add `linux-docker-container` using:

```yaml
image: docker:29.2.1-cli
services:
  - name: docker:29.2.1-dind
    alias: docker
variables:
  DOCKER_HOST: "tcp://docker:2375"
  DOCKER_TLS_CERTDIR: ""
```

Install `python3 py3-pip git`, install uv 0.11.1, run `uv sync --locked`, then the Docker preflight commands.

- [x] **Step 2: Run marked tests and validate JUnit**

Create `artifacts/ci`, run the marker command, then use a YAML block scalar with `python - <<'PY'` to parse XML. Sum all `testsuite` attributes and assert:

```python
assert tests == 10, counts
assert failures == 0, counts
assert errors == 0, counts
assert skipped == 0, counts
```

Publish `artifacts/ci/container-junit.xml` under both `artifacts.paths` and `artifacts.reports.junit`.

- [x] **Step 3: Run all CI structural contracts**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q tests/test_continuous_verification.py -k 'ci or container_module'`

Expected: PASS.

- [x] **Step 4: Commit Docker CI**

```bash
git add .gitlab-ci.yml tests/test_continuous_verification.py
git commit -m "ci: require real Linux Docker container tests"
```

### Task 5: Platform matrix and public documentation

**Files:**
- Create: `docs/platform-support.md`
- Create: `milestones/milestone_024.md`
- Modify: `milestones/latest`
- Modify: `README.md`
- Modify: `ACTION_PLAN.md`
- Test: `tests/test_continuous_verification.py`

**Interfaces:**
- Consumes: status model and evidence rules from Design Doc.
- Produces: public platform state, M24 status and next-step routing.

- [x] **Step 1: Write the platform matrix**

Document status definitions and these rows exactly:

```markdown
| Linux amd64/arm64 + Docker Engine | P0 | configured |
| Linux + rootless Podman | P1 | scheduled |
| Windows native | P2 | deferred |
| macOS arm64 + Docker Desktop Linux daemon | non-release | supplemental |
```

For each row include prerequisites, current evidence, limitations and the next Comet change trigger. State that only a dated Linux runner 10/10 result may promote Linux Docker to `verified`.

- [x] **Step 2: Create M24 milestone and update public status**

Create milestone sections matching `MILESTONE_GUIDE.md`, update `milestones/latest` to `milestone_024.md`, add README sections linking `.gitlab-ci.yml` and the platform matrix, and add an M24 row to ACTION_PLAN. Keep M23's `2305 passed, 10 skipped` and all older historical counts unchanged.

- [x] **Step 3: Run documentation contracts**

Run: `UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q tests/test_continuous_verification.py tests/test_collaboration_docs.py`

Expected: PASS.

- [x] **Step 4: Commit documentation**

```bash
git add docs/platform-support.md milestones/milestone_024.md milestones/latest README.md ACTION_PLAN.md tests/test_continuous_verification.py
git commit -m "docs: define M24 platform evidence matrix"
```

### Task 6: Real Docker evidence and repository gates

**Files:**
- Modify: `docs/platform-support.md`
- Modify: `milestones/milestone_024.md`
- Modify: `openspec/changes/m24-continuous-verification-platform-matrix/tasks.md`
- Create: `docs/superpowers/reports/2026-07-27-m24-continuous-verification-platform-matrix-verify.md`

**Interfaces:**
- Consumes: completed CI/marker/docs implementation.
- Produces: dated local Docker evidence, verification report and completed tasks.

- [x] **Step 1: Run the ten real Docker tests with JUnit**

Run outside filesystem sandbox if needed:

```bash
docker info
docker image inspect python:3.11-slim
mkdir -p /tmp/forgeagent-m24-evidence
UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q \
  tests/test_container_backend.py -m container_integration \
  --junitxml=/tmp/forgeagent-m24-evidence/container-junit.xml
```

Expected: `10 passed`, no skipped. Parse JUnit with the same standard-library logic and record host/daemon/image identifiers in platform docs as `supplemental` evidence.

- [x] **Step 2: Run focused and complete offline gates**

Run:

```bash
UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q tests/test_continuous_verification.py tests/test_container_backend.py tests/test_packaging.py
UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m24-golden-final
openspec validate m24-continuous-verification-platform-matrix --strict
openspec validate --all --strict
UV_CACHE_DIR=/tmp/forgeagent-m24-uv-cache uv build --out-dir /tmp/forgeagent-m24-build-final
git diff --check
```

Expected: all exit 0; Golden report says 20/20; full pytest may have environment-specific non-container skips but the separate Docker evidence is 10/10.

- [x] **Step 3: Perform two self-reviews and fix findings**

Review 1: compare every OpenSpec scenario with CI/tests/docs evidence; verify no platform is overclaimed.

Review 2: inspect `.gitlab-ci.yml` for shell/YAML hazards, version mismatch, artifacts, DinD readiness, hidden allow-failure, JUnit aggregation and offline reproducibility. Fix findings and rerun affected gates.

- [x] **Step 4: Complete task tracking and write verification report**

Check all 8 OpenSpec tasks, write the full verification report with actual commands/results and explicit “GitLab pipeline 未在本地运行” limitation, then run Comet verify/archive.

- [x] **Step 5: Commit verification evidence**

```bash
git add docs/platform-support.md milestones/milestone_024.md openspec/changes/m24-continuous-verification-platform-matrix/tasks.md docs/superpowers/reports/2026-07-27-m24-continuous-verification-platform-matrix-verify.md
git commit -m "test: verify M24 continuous validation gates"
```

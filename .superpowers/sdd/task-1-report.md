# M28 Task 1 实施报告

## 状态

DONE_WITH_CONCERNS

Task 1 已实现并提交。实现 commit：`9586c70`（`feat: add installed-wheel release candidate smoke`）。

## 交付文件

- `scripts/m28_release_candidate_smoke.py`
- `tests/test_m28_release_candidate_smoke.py`

实现提供固定 schema/check names、wheel metadata 与 SHA-256 校验、secret/import 环境清洗、原子 JSON 报告、真实 console/loopback HTTP/Single-Duo-Triad 离线检查、父进程 clean venv 安装与 isolated 子进程入口，以及公开/私有 CLI 参数路由。没有新增依赖、产品子命令、运行时抽象或产品 API 变更。

## TDD 证据

### RED 1：metadata、环境与报告合同

命令：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py -k 'environment or report or wheel'
```

预期失败摘要：pytest collection 以 exit 2 失败；按路径导入不存在的 `scripts/m28_release_candidate_smoke.py`，得到 `FileNotFoundError`。尚未存在生产实现。

### GREEN 1

同一命令通过：`11 passed in 0.14s`。

### RED 2：真实入口与父/子流程合同

命令：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py -k 'cli or http or collaboration or installed or parent or main'
```

预期失败摘要：`9 failed, 11 deselected`；缺少 `check_cli`、`check_http`、`check_collaboration`、`run_installed`、`run_parent`、`main` 及其所需模块入口。

### GREEN 2

同一命令最终通过：`9 passed, 11 deselected in 0.92s`。实现过程中先发现并最小修正 `AssistantMessage.usage` 必填和公开 `CollaborationReport` 不存在 `plan_digest` 字段；测试未为实现而弱化，Triad 仍验证真实计划提交、确认、Generator/Evaluator、完成状态和计数。

计划示例最初使用了运行时不存在的字段 `description`/`evidence`。Controller 已裁决并回写计划，Task 1 使用实际稳定协议：Planner `{id, behavior, acceptance}`，Evaluator `{id, passed, observed, expected, location}`；未扩展产品 API。

### 补充 RED/GREEN：父进程失败证据

命令：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py -k 'run_parent'
```

RED：`3 failed, 18 deselected`，证明 subprocess 输出尚未捕获、无效 wheel 未标记 `clean-wheel: failed`、子失败报告会被父异常分支覆盖。最小修复后 GREEN：`3 passed, 18 deselected`。

随后用单一合同证明子进程非零时不能保留 `passed: true` 报告。RED 为 `1 failed, 21 deselected`；修复后父流程组合 GREEN 为 `4 passed, 18 deselected`。

### 调试回归

第一次最终相邻验证得到 `1 failed, 173 passed`：HTTP smoke 返回后仍短暂存在 `forgeagent-task_0`。根因是 `TaskService.shutdown()` 使用 `ThreadPoolExecutor.shutdown(wait=False)`，方法返回不等于 worker thread 对象已经退出。按现有相邻测试模式改为有界条件轮询自身新增的 `m28-http-smoke`/`forgeagent-task` 线程；focused HTTP 回归为 `1 passed, 21 deselected`。

## 最终验证

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py tests/test_http_server.py tests/test_http_task_service.py tests/test_collaboration_runner.py
```

结果：`174 passed in 6.98s`。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
```

结果：`All checks passed!`。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
```

结果：`2 files already formatted`。

提交前 `git diff --cached --check` 通过；commit 成功创建为 `9586c70`。

## 自审

- 需求映射：六个固定检查、报告状态、环境清洗、wheel identity、原子 replace、CLI/HTTP/协作、父/子模式和固定 stderr 均有测试。
- Ponytail：只使用标准库与现有 ForgeAgent API；无依赖、产品命令、新配置面、wrapper/adapter/factory/manager 抽象。
- 安全：不复制异常、subprocess stdout/stderr、goal、模型回复、路径或环境到报告；provider secret 和 Python import 覆盖在子环境中移除；HTTP 验证无 token 401 且不创建 record。
- 生命周期：subprocess 均 `shell=False` 且有界 timeout；HTTP server、service、worker 和 collaboration runner 均在 `finally` 中关闭并验证无自有线程残留。
- 失败一致性：任一子检查失败时后续保持 `not-run`；父进程拒绝非零 child 携带的假全通过报告，并原子改写为有界失败报告。
- 范围：实现 commit 只包含两个获准文件；未改 plan、OpenSpec、进度文件或现有未跟踪文件。

## 风险信号

- 跨模块：**YES**。Harness 装配 packaging/CLI/HTTP/Task/Collaboration 多个既有边界；产品模块未修改，focused + adjacent 174 项通过。
- 安全：**YES**。涉及 credential scrub、isolated import provenance、HTTP bearer auth 和报告泄密边界；已有正反合同，但本 Task 未进行外部安全审计。
- 并发：**YES**。HTTP server thread 与 TaskService worker/cleanup 生命周期存在并发；曾实际捕获线程退出竞态，现以有界条件轮询修复并回归通过。
- API：**NO**。未新增或修改 ForgeAgent 产品 API/CLI；只新增仓库级发布工程脚本。脚本自身接口由 Task 1 brief 固定。
- diff > 200：**YES**。提交为 2 个新文件、825 行；主要体积来自真实入口集成测试和标准库 HTTP/venv harness。未为压缩行数抽取跨文件 helper 或新抽象。
- DONE_WITH_CONCERNS：**YES**。原因是跨模块、安全、并发与大 diff 风险信号存在；不是未通过测试。Task 1 尚未从真实构建 wheel 完整执行 `run_parent()`，该 packaging/Linux Docker 实证属于后续 Task 2；本 Task 的父流程使用受控 subprocess 合同，真实 CLI/HTTP/协作入口已在当前安装环境运行。

## Reviewer 关注点

- 检查 `run_parent()` 在 venv 创建或 pip install 失败时统一归类 `clean-wheel` 是否符合预期发布口径。
- 检查 3 秒 HTTP worker/thread 退出上限在最低规格 Linux runner 上是否合理。
- Task 2 必须用真实 wheel 执行完整父/子 harness，验证 clean install、console provenance 和 package resources；不得把本 Task 的受控父流程测试当作该证据。

## Review Fix Round 1

Reviewer 的三个 Important finding 已按根因修复；没有扩大文件或产品 API 范围。

### 根因

- 父进程在 child 非零时仍复制 child 自报状态，因此不可信的 `passed` 可以残留。
- 清洗环境只传给 installed child，venv 与 pip 仍继承宿主 import/provider 环境。
- metadata、SHA-256 与 pip 分别重开并使用调用者路径，无法证明它们对应同一份 wheel 字节。

### RED 证据

以下 focused tests 均在修改生产脚本前运行并按目标原因失败：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py::test_wheel_identity_rejects_symlink
```

结果：`1 failed`，现有 `path.stat()` 跟随 symlink，未抛出 `ValueError`。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py::test_run_parent_uses_bounded_isolated_subprocesses
```

结果：`1 failed`，venv subprocess 的 kwargs 缺少 `env`（`KeyError: 'env'`）。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py::test_run_parent_installs_the_validated_snapshot
```

结果：`1 failed`，替换原 wheel 后仍安装调用者路径，父流程返回 1。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py::test_run_parent_never_keeps_passed_report_after_child_failure
```

结果：`1 failed`，`cli/http/single/duo/triad` 错误保留为 `passed`。

### GREEN 与实现

- `lstat()` 和 `O_NOFOLLOW`（平台提供时）拒绝 symlink；从一次打开的普通文件 handle 复制到临时 wheel snapshot，再只对 snapshot 做 metadata、SHA-256 与 pip install。
- 在临时 HOME 创建后生成一次 cleaned environment，并将同一 mapping 传给 venv、pip、installed child 三个 subprocess。
- installed child 非零时不再信任其报告，统一写 `clean-wheel=failed`，后五项 `not-run`，`passed=false`。

五个新增/加强的 focused contracts 首次 GREEN：`5 passed in 0.09s`。格式化后完整 Task 1 focused suite：`24 passed in 1.00s`。

### 最终回归

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py tests/test_http_server.py tests/test_http_task_service.py tests/test_collaboration_runner.py
```

结果：`176 passed in 6.96s`。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
```

结果：`All checks passed!`；`2 files already formatted`。

风险信号仍为跨模块、安全、并发、累计 diff > 200；本轮未新增依赖、产品接口、配置面或抽象。Task 2 仍需用真实构建 wheel 完整执行父/子流程。

## Review Fix Round 2

Reviewer 发现零退出 child 的非精确报告仍会被部分复制，导致失败检查之后保留不可能的 `passed` 状态。根因是父进程只拒绝报告整体，却继续信任其逐项状态；而 child exit 0 只允许固定 schema/digest、`passed=true` 和六项全 `passed` 这一种结果。

### RED

先新增 `test_run_parent_rejects_contradictory_zero_exit_report`，让 child 返回 0 并写入 `cli=failed`、其余 `passed` 的矛盾报告：

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py::test_run_parent_rejects_contradictory_zero_exit_report
```

结果：`1 failed`。实际报告保留了 `clean-wheel/http/single/duo/triad=passed`，stderr 为 `M28 RC smoke failed: cli`，精确复现 reviewer finding。

### GREEN 与最小修复

删除非精确报告的逐项复制逻辑；任何非固定全通过报告统一写成 `clean-wheel=failed`、其余五项 `not-run`、`passed=false`，stderr 固定为 `M28 RC smoke failed: clean-wheel`。focused test 结果：`1 passed in 0.11s`；完整 Task 1 suite：`25 passed in 1.06s`。

### 最终回归

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py tests/test_http_server.py tests/test_http_task_service.py tests/test_collaboration_runner.py
```

结果：`177 passed in 6.96s`。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
```

结果：`All checks passed!`；`2 files already formatted`。`git diff --check` 通过。

风险信号不变：跨模块、安全、并发、累计 diff > 200；本轮净删除生产分支复杂度，未新增依赖、产品接口、配置面或抽象。

## Completion Contract Correction

最终复核发现父进程的零退出成功条件没有验证固定 `version`、子进程 `python` 或顶层字段精确集合，因此格式不完整或带额外字段的报告仍可能被接受。

### RED

先新增一个六种变异的参数化合同，分别删除必需字段、增加未知字段、修改版本，以及令 Python 版本缺失、格式错误或低于 3.11：

```bash
uv run pytest -q tests/test_m28_release_candidate_smoke.py::test_run_parent_rejects_malformed_zero_exit_report
```

结果：`6 failed in 0.13s`；六种情况下 `run_parent()` 均错误返回 0，精确复现接收条件缺口。

### GREEN 与最小修复

成功报告现在必须具有精确顶层字段集合 `{schema, version, python, wheel_sha256, passed, checks}`、固定版本 `0.1.0`，并包含语义格式为 `major.minor.patch` 且不低于 3.11.0 的 Python 版本。没有新增子进程或将自报 JSON 当作密码学证明。

focused 结果：`7 passed in 0.10s`，包括六个拒绝合同和既有精确报告成功路径。

### 最终验证

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_candidate_smoke.py tests/test_http_server.py tests/test_http_task_service.py tests/test_collaboration_runner.py
```

结果：`183 passed in 6.99s`。

```bash
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check scripts/m28_release_candidate_smoke.py tests/test_m28_release_candidate_smoke.py
```

结果：`All checks passed!`；`2 files already formatted`。`git diff --check` 通过。

风险信号不变：跨模块、安全、并发、累计 diff > 200；本轮仅收紧已有报告成功谓词和对应测试，未新增依赖、产品接口、配置面或抽象。

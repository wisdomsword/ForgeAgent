---
change: extract-cli-boundaries
design-doc: docs/superpowers/specs/2026-07-31-cli-boundary-extraction-design.md
base-ref: a2c9925f471cd76a0411befd1902793786258595
---

# M41 CLI Boundary Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在所有 CLI、REPL、HTTP 与测试契约不变的前提下，把 `forgeagent.cli` 拆成四个有界内部模块并满足六项 Rewrite/Dependency 阈值。

**Architecture:** `forgeagent.cli` 保留入口和兼容 façade；纯 parser/config 函数直接 re-export，Collaboration、REPL 和 HTTP 入口由薄 wrapper 在每次调用时构造冻结 bindings。四个内部模块只依赖现有领域模块，彼此不形成依赖环，也不反向导入 `forgeagent.cli`。

**Tech Stack:** Python 3.11+、stdlib `argparse`/`http.server`、Pydantic v2、Rich、pytest、Ruff、uv；不新增依赖。

## Global Constraints

- `src/forgeagent/cli.py` 最终不超过 1800 行；每个新边界模块不超过 900 行。
- 运行时直接依赖保持 8 项；禁止新增框架、注册器、service locator 或代码生成。
- 七个帮助入口的 exit code、stdout/stderr 字节哈希必须与基线一致。
- 保留 `forgeagent.cli` 历史导入和 monkeypatch 位置；wrapper 必须在每次调用时解析当前 globals。
- 不改变命令、参数、默认值、输出、HTTP shape、资源关闭、配置、数据或发布边界。
- 任一硬阈值最终失败时停止并回退 M41 实现，不改变进入 M41 前的用户工作区改动。

---

### Task 1: 固化结构与兼容门禁

**Files:**
- Create: `tests/test_m41_cli_boundaries.py`
- Modify: `openspec/changes/extract-cli-boundaries/tasks.md`
- Reference: `docs/evaluation/m41/rewrite-dependency-baseline.md`

**Interfaces:**
- Consumes: 基线中的四个模块名、行数阈值和七组帮助哈希。
- Produces: `_boundary_modules()`、帮助哈希回归和静态依赖方向测试。

- [ ] **Step 1: 编写结构 RED 测试**

  新测试断言 `_cli_parser.py`、`_cli_collaboration.py`、`_cli_repl.py`、`_cli_http.py` 存在，`cli.py <= 1800`，每个边界模块 `<= 900`，且边界模块 AST 不导入 `.cli`。

- [ ] **Step 2: 运行 RED 并确认失败原因**

  Run: `uv run pytest -q tests/test_m41_cli_boundaries.py`

  Expected: FAIL，因为四个边界模块尚不存在且 `cli.py` 为 3226 行；不得因语法或 fixture 错误失败。

- [ ] **Step 3: 增加帮助输出 characterization 测试**

  对 `--help`、`run --help`、`loop --help`、`serve --help`、`evaluate --help`、`models --help`、`smoke --help` 运行 `python -m forgeagent.cli`，核对 exit、stdout/stderr SHA-256。

- [ ] **Step 4: 运行既有边界基线**

  Run: `uv run pytest -q tests/test_cli.py tests/test_collaboration_integrations.py tests/test_http_task_service.py`

  Expected: `349 passed`。

- [ ] **Step 5: 勾选 OpenSpec 1.1，提交基线与 RED 门禁**

  Commit: `test: establish M41 CLI extraction gates`

### Task 2: 提取 parser/config 边界

**Files:**
- Create: `src/forgeagent/_cli_parser.py`
- Modify: `src/forgeagent/cli.py`
- Test: `tests/test_m41_cli_boundaries.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing evaluation models and constants through direct stable imports.
- Produces: `build_parser()`, `load_strict_json()`, `validate_artifact_manifest()`, `run_evaluator()`, `evaluation_record()`, `metric_text()`, `append_trend()`, `render_evaluation()`, `run_evaluate_command()`; `cli.py` re-exports historical underscored names.

- [ ] **Step 1: 让 parser 模块存在性与 re-export 测试保持 RED**

  增加 `forgeagent.cli.build_parser is forgeagent._cli_parser.build_parser` 及历史 helper 可调用断言，运行定向测试并确认模块缺失失败。

- [ ] **Step 2: 移动 parser/evaluation 纯实现并建立 re-export**

  保持原函数体和 argparse 调用顺序不变；只改名称映射，不改 help/默认值。

- [ ] **Step 3: 运行 GREEN**

  Run: `uv run pytest -q tests/test_m41_cli_boundaries.py tests/test_cli.py`

  Expected: 只有尚未提取的三个结构断言失败；parser/help 断言通过。

- [ ] **Step 4: 运行 Ruff 并提交**

  Run: `uv run ruff check src/forgeagent/_cli_parser.py src/forgeagent/cli.py tests/test_m41_cli_boundaries.py`

  Commit: `refactor: extract CLI parser boundary`

### Task 3: 提取 Collaboration adapter 边界

**Files:**
- Create: `src/forgeagent/_cli_collaboration.py`
- Modify: `src/forgeagent/cli.py`
- Test: `tests/test_m41_cli_boundaries.py`
- Test: `tests/test_collaboration_integrations.py`

**Interfaces:**
- Produces: frozen `CollaborationBindings`; internal `run_collaboration_once(..., bindings=...)`; façade 保留原 `run_collaboration_once`、`_render_collaboration_report`、`_console_plan_confirmer`、`_confirmed_collaboration_mode` 名称和签名。

- [ ] **Step 1: 编写当前调用替换 RED 测试**

  替换 `forgeagent.cli._validate_client_context_policy` 或 `Task`，调用 façade 后断言 replacement 被使用；在迁移 wrapper 出现前测试应因缺少 `CollaborationBindings`/内部入口失败。

- [ ] **Step 2: 移动实现并添加最小 bindings wrapper**

  仅把真实可替换 class/callback 放入 bindings；报告模型和稳定纯函数直接从领域模块导入。

- [ ] **Step 3: 运行 GREEN 与协作专项**

  Run: `uv run pytest -q tests/test_m41_cli_boundaries.py tests/test_collaboration_integrations.py tests/test_collaboration_runner.py tests/test_collaboration_stop_projection.py`

- [ ] **Step 4: Ruff、勾选 2.2 并提交**

  Commit: `refactor: extract CLI collaboration adapter`

### Task 4: 提取 REPL 边界

**Files:**
- Create: `src/forgeagent/_cli_repl.py`
- Modify: `src/forgeagent/cli.py`
- Test: `tests/test_m41_cli_boundaries.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_cli_startup_blackbox.py`

**Interfaces:**
- Produces: frozen `ReplBindings`; internal `repl(..., bindings=...)`; façade 保留原 `repl` 签名和 slash handler monkeypatch 路径。

- [ ] **Step 1: 编写 REPL 当前调用 RED 测试**

  替换 `forgeagent.cli.build_mcp_manager` 与 `run_once`，驱动一轮注入 reader，断言替换函数被调用且 manager 被关闭。

- [ ] **Step 2: 移动 reader/startup display/REPL loop 并添加 wrapper**

  迁移原 `try/finally` 整体；bindings 包含 slash handlers、身份/Memory/Skill 和执行入口，不复制会话状态。

- [ ] **Step 3: 运行 GREEN 与 REPL 专项**

  Run: `uv run pytest -q tests/test_m41_cli_boundaries.py tests/test_cli.py tests/test_cli_startup_blackbox.py tests/test_identity.py tests/test_skills.py`

- [ ] **Step 4: Ruff、勾选 2.3 并提交**

  Commit: `refactor: extract CLI REPL boundary`

### Task 5: 提取 HTTP/client 边界

**Files:**
- Create: `src/forgeagent/_cli_http.py`
- Modify: `src/forgeagent/cli.py`
- Test: `tests/test_m41_cli_boundaries.py`
- Test: `tests/test_http_server.py`
- Test: `tests/test_http_task_service.py`

**Interfaces:**
- Produces: `HttpStartupError`, `HttpRuntimeSettings`, frozen `HttpBindings`; internal client/context helpers and `serve_http(..., bindings=...)`; façade 保留历史名称与异常捕获。

- [ ] **Step 1: 编写 HTTP 当前调用 RED 测试**

  替换 `forgeagent.cli.build_real_client`/`_validate_context_policy` 或 owned server callback，调用 façade 并断言替换在当前调用生效。

- [ ] **Step 2: 移动 HTTP/client 装配并添加 wrapper**

  原配置 key 集、错误边界、signal、shutdown、receipt/Loop/Collaboration 装配和 `try/finally` 顺序逐字保持。

- [ ] **Step 3: 运行 GREEN 与 HTTP 专项**

  Run: `uv run pytest -q tests/test_m41_cli_boundaries.py tests/test_http_server.py tests/test_http_task_service.py tests/test_loop_runner.py tests/test_collaboration_integrations.py tests/test_cli.py`

- [ ] **Step 4: Ruff、勾选 2.4 并提交**

  Commit: `refactor: extract CLI HTTP boundary`

### Task 6: 六项阈值、复审和里程碑收尾

**Files:**
- Modify: `docs/evaluation/m41/rewrite-dependency-baseline.md`
- Create: `docs/superpowers/reports/2026-07-31-cli-boundary-extraction-verify.md`
- Modify: `ACTION_PLAN.md`
- Create: `milestones/milestone_041.md`
- Modify: `milestones/latest`
- Modify: `openspec/changes/extract-cli-boundaries/tasks.md`

**Interfaces:**
- Consumes: 四个边界实现和全部基线。
- Produces: 同口径最终测量、两轮复审记录、M41 续接指引。

- [ ] **Step 1: 运行结构、依赖、帮助与性能复测**

  使用基线相同命令；必须满足 `cli.py <= 1800`、每模块 `<= 900`、依赖 8、帮助 hash 相同、两个性能中位数不超过 136.140/0.672 ms。

- [ ] **Step 2: 运行聚焦和全量门禁**

  Run: `uv run pytest -q`

  Run: `uv run ruff check .`

  Run: `uv run ruff format --check .`

  Run: `uv build`

  Run: `git diff --check`

  Run: `openspec validate --all --strict`

- [ ] **Step 3: 做两轮最终自审并修复发现**

  第一轮逐调用检查 façade/bindings/资源所有权；第二轮检查结构阈值、循环依赖、YAGNI、文档/规格/任务一致性和既有工作区隔离。任一修复后重跑受影响专项及全量门禁。

- [ ] **Step 4: 写验证报告和 M41 台账**

  记录原始数量、性能/结构差值、skip、所有已知限制及“不执行 PyPI/tag/push/发布自动化”。

- [ ] **Step 5: 完成 standard code review、勾选全部 tasks 并提交**

  Commit: `docs: complete M41 CLI boundary extraction`

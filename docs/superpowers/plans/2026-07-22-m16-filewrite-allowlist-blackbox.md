# M16 FileWrite Allowlist Blackbox Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供一个单命令真实模型黑盒脚本，验证空 HTTP allowlist 拒绝目标 FileWrite、精确 `file/m16-allowlist.txt` 允许同一操作。

**Architecture:** Bash 脚本拥有两个临时 `forgeagent serve` 进程，通过真实 HTTP API 提交同一目标并以 JSONL 审计作为权威判据。pytest 使用临时 fake `forgeagent` HTTP server 驱动相同控制流，不调用真实模型，用于验证 PASS 和 INCONCLUSIVE 退出语义。

**Tech Stack:** Bash 3.2+、curl、jq、Python 3.11+、pytest、ForgeAgent CLI。

## Global Constraints

- 不修改 ForgeAgent 产品代码、HTTP 协议或 allowlist 语义。
- 真实运行使用动态 loopback 端口和独立临时目录，不影响现有 `8765` 服务。
- 两阶段目标文本必须逐字相同，内嵌唯一、完整的 FileWrite ToolCall 标记及精确
  `path`/`content`，并明确禁止模型改用 Exec、MCP、Python、shell 或其他工具。
- bearer token 临时生成且不得写入配置、输出或审计。
- 模型未调用目标 FileWrite、出现额外成功工具或产生目标外 artifact 时退出码为
  `2`（INCONCLUSIVE），不得误报 PASS/FAIL；目标 FileWrite 后的额外失败工具
  只保留为诊断，不覆盖已经形成的 allowlist 证据。
- PASS 为 `0`，确定性产品/契约失败为 `1`；所有退出路径保留证据目录并清理后台服务。

---

### Task 1: 真实模型 FileWrite Allowlist 黑盒脚本

**Files:**
- Create: `scripts/m16-filewrite-allowlist-blackbox.sh`
- Create: `tests/test_m16_filewrite_allowlist_blackbox.py`

**Interfaces:**
- Consumes: `.venv/bin/forgeagent serve --config PATH`、`POST /tasks`、`GET /tasks/{id}`、JSONL `confirmation.decision`/`tool.operation`。
- Produces: `scripts/m16-filewrite-allowlist-blackbox.sh`；环境覆盖项 `M16_MODEL`、`M16_TIMEOUT_SECONDS`、`M16_EVIDENCE_DIR`、`M16_FORGEAGENT_BIN`、`M16_PYTHON_BIN`；退出码 `0/1/2`。

- [ ] **Step 1: 写 PASS 与 INCONCLUSIVE 失败测试**

测试创建临时 fake `forgeagent` 可执行文件。fake 读取脚本生成的 config，监听指定 loopback 端口，并按 `FAKE_M16_MODE` 写入确定性 HTTP 响应、审计和目标文件：

- `write_fake_forgeagent(tmp_path: Path) -> Path` 写入一个带当前 Python shebang 的可执行脚本。
- fake 只实现 `serve --config PATH`，从脚本生成的简单 YAML 中读取 `port`、`allowed_root`、`audit_path` 和 allowlist。
- `POST /tasks` 返回固定 task id；`GET /tasks/{id}` 返回 `completed`。
- `filewrite` 模式写入用同一 operation id 关联的 confirmation/tool 事件；精确 allowlist 阶段额外写入目标文件。
- `no-filewrite` 模式只写 LLM outcome，供主脚本判定 INCONCLUSIVE。

```python
def run_script(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "M16_FORGEAGENT_BIN": str(write_fake_forgeagent(tmp_path)),
        "M16_PYTHON_BIN": sys.executable,
        "M16_EVIDENCE_DIR": str(tmp_path / "evidence"),
        "M16_TIMEOUT_SECONDS": "5",
        "FAKE_M16_MODE": mode,
    }
    return subprocess.run(
        ["bash", "scripts/m16-filewrite-allowlist-blackbox.sh"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_blackbox_script_passes_exact_two_phase_contract(tmp_path: Path) -> None:
    result = run_script(tmp_path, "filewrite")
    assert result.returncode == 0
    assert "PASS: empty allowlist denied FileWrite" in result.stdout
    assert "PASS: exact allowlist preapproved FileWrite" in result.stdout


def test_blackbox_script_reports_model_tool_drift_as_inconclusive(tmp_path: Path) -> None:
    result = run_script(tmp_path, "no-filewrite")
    assert result.returncode == 2
    assert "INCONCLUSIVE" in result.stderr
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/test_m16_filewrite_allowlist_blackbox.py
```

Expected: FAIL，因为 `scripts/m16-filewrite-allowlist-blackbox.sh` 尚不存在。

- [ ] **Step 3: 实现最小两阶段脚本**

脚本必须包含以下接口和控制流：

- `stop_server()`：对当前子进程发送 TERM，在有界等待后必要时 KILL，并 `wait` 回收。
- `fail(message)` / `inconclusive(message)`：先打印当前 task 的审计证据和证据目录，再分别以 1/2 退出。
- `find_port()`：用 `M16_PYTHON_BIN` 在 `127.0.0.1:0` 获取动态端口后立即关闭探针 socket。
- `write_config(phase, port, allow)`：生成不含 token 的 server-owned YAML；两个阶段除 audit path、port 和 allowlist 外完全相同。
- `start_server(phase, allow)`：后台启动 `forgeagent serve`，用带正确 bearer token 的不存在路径轮询 `404` 作为 readiness，启动失败打印服务日志。
- `submit_task()`：只提交固定 `goal`，要求 HTTP 202，并保存 task id。
- `poll_terminal()`：查询到非 queued/running 状态，保存完整终态 JSON；超过 `M16_TIMEOUT_SECONDS` 以 FAIL 退出。
- `has_decision(decision)`：只匹配当前 task、`file/m16-allowlist.txt` 和指定 decision。
- `has_matching_tool_result(decision, status)`：按下面 jq 使用 operation id 联结 FileWrite confirmation 与 tool 事件。
- `run_denied_phase()`：拒绝任何目标 preapproved；目标 denied + matching failed + 文件不存在才 PASS；无目标 FileWrite 或出现替代落盘为 INCONCLUSIVE。
- `run_allowed_phase()`：目标 denied 为 FAIL；无 preapproved 为 INCONCLUSIVE；matching success、精确内容、0600 审计且 token 不在审计中才 PASS。
- EXIT/INT/TERM trap 始终调用 `stop_server`；两个阶段 PASS 后输出总 PASS 和证据目录。

权威 jq 联结使用同一 `operation_id` 关联 confirmation 与 tool 事件：

```jq
. as $events
| [$events[] | select(
    .task_id == $task
    and .event_type == "confirmation.decision"
    and .parameters.operation == "file/m16-allowlist.txt"
    and .result_status == $decision
  )] as $decisions
| any($decisions[];
    .operation_id as $operation
    | any($events[];
        .task_id == $task
        and .event_type == "tool.operation"
        and .operation_id == $operation
        and .parameters.tool == "FileWrite"
        and .result_status == $tool_status
      )
  )
```

- [ ] **Step 4: 运行测试并确认 GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/test_m16_filewrite_allowlist_blackbox.py
bash -n scripts/m16-filewrite-allowlist-blackbox.sh
```

Expected: `2 passed`，Bash 语法检查退出 0。

- [ ] **Step 5: 运行相关回归和静态检查**

Run:

```bash
PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_m16_filewrite_allowlist_blackbox.py \
  tests/test_headless.py \
  tests/test_http_server.py \
  tests/test_cli.py::test_serve_task_factory_does_not_inherit_mcp_auto_approve
.venv/bin/ruff check tests/test_m16_filewrite_allowlist_blackbox.py
.venv/bin/ruff format --check tests/test_m16_filewrite_allowlist_blackbox.py
git diff --check
```

Expected: 全部通过；loopback bind 受限环境仅允许既有明确 skip。

- [ ] **Step 6: 提交**

```bash
git add scripts/m16-filewrite-allowlist-blackbox.sh \
  tests/test_m16_filewrite_allowlist_blackbox.py \
  docs/superpowers/plans/2026-07-22-m16-filewrite-allowlist-blackbox.md
git commit -m "test: add M16 FileWrite allowlist blackbox smoke"
```

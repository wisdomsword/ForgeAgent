---
change: expose-task-execution-evidence
design-doc: docs/superpowers/specs/2026-08-04-task-execution-evidence-design.md
base-ref: dfad978d82434b493b17332721484f4e54afedb8
---

# Task Execution Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每个 ForgeAgent Task 保留已尝试工具及实际执行程序的安全、持久、可追溯证据，并在 CLI、HTTP、Loop、Duo、Triad 的终态结果中提供有界投影。

**Architecture:** 新增 `execution_evidence.py` 作为唯一共享边界，包含不可变证据模型、Task 内 recorder、安全公开投影、聚合函数、程序制品 store 和本地引用解析器。`Step._dispatch()` 记录真正到达 dispatch 的工具；`ExecTool.run()` 在 backend 前 fail-closed 落盘；Task、Loop、Collaboration 分别把同一模型投影到即时结果和 durable state，入口只负责终态渲染或安全序列化。

**Tech Stack:** Python 3.11+、Pydantic v2、标准库 `os`/`stat`/`pathlib`/`threading`、pytest、Ruff、uv、OpenSpec/Comet；不新增依赖。

## Global Constraints

- 实现基线固定为 `dfad978d82434b493b17332721484f4e54afedb8`，只实现 `expose-task-execution-evidence` delta specs。
- 每个生产行为修改必须先有可观察的 RED 测试；RED 原因必须对应缺失契约，不能来自测试夹具错误。
- 只记录到达 `Step._dispatch()` 的工具；解析后因完成边界或取消而未 dispatch 的工具不得出现。
- 每个 Exec 在 trusted、restricted、container backend dispatch 前持久化实际选中代码；持久化失败不得调用 backend。
- 程序目录固定为 `<project-root>/.forgeagent/execution-artifacts/<execution-id>/programs/`；程序保留不随 Task、HTTP record、Loop 或 Collaboration close 删除。
- 每 Task 最多 100 个程序、单程序 UTF-8 最多 1 MiB、总 UTF-8 最多 8 MiB；内部 recorder 保留前 128 条，公开和 durable 聚合保留前 32 条。
- HTTP 只返回 `execution-artifacts/...` POSIX 相对引用，不增加读取或下载 route；本地 CLI 才能显示宿主绝对路径。
- 公开证据不得包含原始参数、代码、stdout/stderr、prompt、secret、文件内容、raw exception 或非本地绝对路径。
- `TaskOutcome`、`LoopCheckpoint`、`LoopReport`、`CollaborationState`、`CollaborationReport` 只增加带空默认值的字段；既有状态枚举、schema 字符串和 v1 durable 文件保持兼容。
- `.forgeagent/execution-artifacts/` 是运行时数据，必须加入 `.gitignore`，不得进入提交。

---

### Task 1: 建立证据模型、Task recorder 与安全投影

**Files:**
- Create: `src/forgeagent/execution_evidence.py`
- Create: `tests/test_execution_evidence.py`

**Interfaces:**
- Produces: `EvidenceStatus = Literal["succeeded", "failed", "artifact_persistence_failed"]`。
- Produces: `EvidenceRole = Literal["planner", "generator", "evaluator"]`；共享模块不得导入 `collaboration.py`。
- Produces: `ProgramArtifact(reference: str, local_path: Path | None = Field(default=None, exclude=True))`；`local_path` 永不进入 `model_dump()`。
- Produces: `ToolExecutionRecord(sequence: int, tool: str, status: EvidenceStatus, block: str | None = None, artifact: ProgramArtifact | None = None, iteration: int | None = None, role: Literal["planner", "generator", "evaluator"] | None = None, attempt: int | None = None)`。
- Produces: `ExecutionEvidence(records: tuple[ToolExecutionRecord, ...] = (), truncated: bool = False, omitted_count: int = 0)`。
- Produces: `ExecutionEvidenceRecorder.append(*, tool: str, success: bool, block_name: str | None, program_artifact: ProgramArtifact | None, status: EvidenceStatus | None) -> None` 与 `snapshot() -> ExecutionEvidence`。
- Produces: `public_execution_evidence(evidence: ExecutionEvidence, *, secret_values: Iterable[str] = (), include_local_paths: bool = False) -> ExecutionEvidence`。
- Produces: `merge_execution_evidence(current: ExecutionEvidence, incoming: ExecutionEvidence, *, iteration: int | None = None, role: EvidenceRole | None = None, attempt: int | None = None, dedupe_cumulative_roles: bool = False) -> ExecutionEvidence`。

- [x] **Step 1: 写证据模型和 recorder 的失败测试**

  在 `tests/test_execution_evidence.py` 写入以下可执行契约：

  ```python
  def test_recorder_keeps_attempt_order_and_first_128_records():
      recorder = ExecutionEvidenceRecorder()
      for index in range(130):
          recorder.append(
              tool=f"tool-{index}",
              success=index % 2 == 0,
              block_name=None,
              program_artifact=None,
              status=None,
          )
      snapshot = recorder.snapshot()
      assert [item.sequence for item in snapshot.records] == list(range(1, 129))
      assert snapshot.truncated is True
      assert snapshot.omitted_count == 2


  def test_program_artifact_local_path_is_excluded_from_nested_dump(tmp_path):
      artifact = ProgramArtifact(
          reference="execution-artifacts/" + "a" * 32 + "/programs/0001-main.py",
          local_path=tmp_path / "private" / "0001-main.py",
      )
      evidence = ExecutionEvidence(
          records=(
              ToolExecutionRecord(
                  sequence=1,
                  tool="Exec",
                  status="succeeded",
                  block="main",
                  artifact=artifact,
              ),
          )
      )
      dumped = evidence.model_dump(mode="json")
      assert "local_path" not in repr(dumped)
      assert str(tmp_path) not in repr(dumped)
  ```

  再增加：显式 `artifact_persistence_failed` 覆盖 success 映射、负 sequence/omitted 拒绝、非法 origin 组合拒绝、空 envelope 序列化稳定的断言。

- [x] **Step 2: 运行模型测试并确认 RED**

  ```bash
  rtk uv run pytest tests/test_execution_evidence.py -q
  ```

  Expected: collection 失败，明确报告 `forgeagent.execution_evidence` 不存在。

- [x] **Step 3: 实现不可变模型和 recorder**

  在 `execution_evidence.py` 固定以下常量和字段，不引入第二套 DTO：

  ```python
  MAX_INTERNAL_EVIDENCE_RECORDS = 128
  MAX_PUBLIC_EVIDENCE_RECORDS = 32
  MAX_EVIDENCE_LABEL_CHARS = 128
  MAX_ARTIFACT_REFERENCE_CHARS = 512


  class ProgramArtifact(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      reference: str
      local_path: Path | None = Field(default=None, exclude=True, repr=False)


  class ExecutionEvidenceRecorder:
      def __init__(self) -> None:
          self._lock = threading.Lock()
          self._next_sequence = 1
          self._records: list[ToolExecutionRecord] = []
          self._omitted_count = 0

      def append(
          self,
          *,
          tool: str,
          success: bool,
          block_name: str | None,
          program_artifact: ProgramArtifact | None,
          status: EvidenceStatus | None,
      ) -> None:
          with self._lock:
              sequence = self._next_sequence
              self._next_sequence += 1
              resolved_status = status or ("succeeded" if success else "failed")
              record = ToolExecutionRecord(
                  sequence=sequence,
                  tool=tool,
                  status=resolved_status,
                  block=block_name,
                  artifact=program_artifact,
              )
              if len(self._records) < MAX_INTERNAL_EVIDENCE_RECORDS:
                  self._records.append(record)
              else:
                  self._omitted_count += 1

      def snapshot(self) -> ExecutionEvidence:
          with self._lock:
              return ExecutionEvidence(
                  records=tuple(self._records),
                  truncated=self._omitted_count > 0,
                  omitted_count=self._omitted_count,
              )
  ```

  Pydantic validators 必须拒绝非 canonical reference、bool 冒充整数、负计数和不完整 origin（role 与 attempt 必须同时有值）；`artifact_persistence_failed` 记录不得携带 artifact。tool/block 先 mask 已知 secret，再把控制/格式字符确定性转义为 `\\xNN`、`\\uNNNN` 或 `\\UNNNNNNNN`，最后截为 128 字符；默认空对象必须能加载旧状态。

- [x] **Step 4: 写公开投影和聚合的失败测试**

  增加测试并断言：前 32 条稳定保留；原 `omitted_count` 与本次裁剪数相加；已知 secret 被 `REDACTED` 替换；控制字符被转义或替换；`include_local_paths=False` 清除本地路径；cumulative collaboration 按 `(role, attempt, sequence)` 去重且不把重复项计入 omitted；新项才附加当前 iteration。

- [x] **Step 5: 实现公开投影和聚合函数并验证 GREEN**

  `public_execution_evidence()` 只复制 tool、block、status、origin 和 canonical reference，不复制其他对象字段。`merge_execution_evidence()` 先为新记录补 origin，再用完整 origin key 稳定去重，最后保留前 32 条并累计真正被截断的唯一记录：

  ```python
  def _origin_key(record: ToolExecutionRecord) -> tuple[object, ...]:
      return (record.iteration, record.role, record.attempt, record.sequence)


  def _cumulative_role_key(record: ToolExecutionRecord) -> tuple[object, ...] | None:
      if record.role is None or record.attempt is None:
          return None
      return (record.role, record.attempt, record.sequence)
  ```

  ```bash
  rtk uv run pytest tests/test_execution_evidence.py -q
  ```

  Expected: 全部通过；序列、截断、mask、local-path exclusion 和 cumulative 去重断言均为 GREEN。

- [x] **Step 6: 提交共享证据模型**

  ```bash
  rtk git add src/forgeagent/execution_evidence.py tests/test_execution_evidence.py
  rtk git commit -m "feat: add bounded task execution evidence models"
  ```

### Task 2: 实现 symlink-safe、原子、限额的程序制品 store

**Files:**
- Modify: `src/forgeagent/execution_evidence.py`
- Modify: `tests/test_execution_evidence.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `ProgramArtifactPersistenceError(Exception)`，公开 message 固定为 `program artifact persistence failed`，不带路径或 raw exception。
- Produces: `ProgramArtifactStore(project_root: str | Path, *, execution_id: str | None = None)`。
- Produces: `ProgramArtifactStore.persist(*, block_name: str, language: str, code: str) -> ProgramArtifact`。
- Produces: `ProgramArtifactStore.close() -> None`，只关闭 descriptor，不删除程序目录或文件。
- Produces: `resolve_local_artifact_path(project_root: str | Path, reference: str) -> Path | None`，只接受 canonical reference 且要求每级目录非 symlink、末端为普通文件。

- [ ] **Step 1: 写精确字节、命名、权限和容量 RED 测试**

  增加以下核心断言，并用参数化补齐第 100/101 个文件、`1 MiB`/`1 MiB+1`、累计 `8 MiB`/超一字节边界：

  ```python
  def test_program_store_persists_exact_utf8_bytes_with_private_modes(tmp_path):
      store = ProgramArtifactStore(tmp_path, execution_id="a" * 32)
      artifact = store.persist(block_name="Main block", language="python", code="print('中')\n")
      assert artifact.reference == (
          "execution-artifacts/" + "a" * 32 + "/programs/0001-main-block.py"
      )
      assert artifact.local_path is not None
      assert artifact.local_path.read_bytes() == "print('中')\n".encode()
      assert stat.S_IMODE(artifact.local_path.stat().st_mode) == 0o600
      assert stat.S_IMODE(artifact.local_path.parent.stat().st_mode) == 0o700
  ```

  增加 block label 包含 path separator、traversal、控制字符、Unicode、已知 secret 时，文件名仍为 bounded ASCII 且不含原值的断言；Python 扩展固定 `.py`，模型 path metadata 不进入 API。

- [ ] **Step 2: 写目录替换、symlink、发布失败和临时清理 RED 测试**

  覆盖 `.forgeagent`、`execution-artifacts`、execution-id、`programs` 任一级预置 symlink；在 temp 写入后用 monkeypatch 模拟目录 rebind；让 `os.write`、`os.fsync`、`os.replace` 分别失败。每例断言：抛出稳定 `ProgramArtifactPersistenceError`、根外 sentinel 不变、没有有效 reference、没有残留 `.tmp-*` 普通文件。

- [ ] **Step 3: 运行 store 测试并确认 RED**

  ```bash
  rtk uv run pytest tests/test_execution_evidence.py -q
  ```

  Expected: store 导入或 `persist()` 断言失败；已有 Task 1 模型测试继续通过。

- [ ] **Step 4: 实现 descriptor-relative 原子发布**

  `ProgramArtifactStore` 构造时只解析 immutable project root 和 UUID，不创建目录。第一次 `persist()` 在锁内执行以下固定顺序：

  1. UTF-8 编码并在任何写入前检查 100/1 MiB/8 MiB 上限。
  2. 打开 project root descriptor；对 `.forgeagent/execution-artifacts/<id>/programs` 每级使用 `dir_fd`、`O_DIRECTORY|O_NOFOLLOW` 和 `fstat`，缺失时以 `0700` 创建后重新安全打开；保存每级 `(st_dev, st_ino)`。
  3. 文件名由四位 Task 内 Exec sequence 与宿主清理 label 组成；label 先 `mask_secrets(..., sensitive_env_values())`，再转成最长 64 字符的 ASCII `[a-z0-9-]`，空值使用 `program`。
  4. 以 `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` 和 `0600` 创建唯一 `.tmp-<uuid>`；循环 `os.write` 写完，`os.fchmod(0o600)`、`os.fsync(file_fd)`、`fstat` 验证普通文件。
  5. 发布前从 pathname 重新 no-follow 遍历一次并比较所有目录 identity；用 `os.replace(temp, final, src_dir_fd=programs_fd, dst_dir_fd=programs_fd)` 发布，`fsync(programs_fd)`，再重新遍历并比较所有目录 identity，同时比较仍打开的 file descriptor 与 `stat(final, follow_symlinks=False)` 的 `(st_dev, st_ino)`。发布前后都必须比较 `lstat(programs_path)` 与 `fstat(programs_fd)` 的 `(st_dev, st_ino)`，任何父目录 pathname rebinding 都必须失败。
  6. 全部成功后才增加文件数和总字节计数并返回 `ProgramArtifact`；绑定变化时通过 held `programs_fd` 删除已发布文件后 fail closed。只把预期的 `OSError`、`UnicodeError`、容量和绑定校验错误转换为稳定错误，best-effort unlink temp/final，`KeyboardInterrupt`/`SystemExit` 保持原样传播。

  `resolve_local_artifact_path()` 必须先经 `ProgramArtifact.reference` validator，再从 project root descriptor 逐级 no-follow 验证，末端只接受 regular file；它不打开网络能力，也不提供 HTTP route。

- [ ] **Step 5: 验证 store GREEN 与运行时忽略规则**

  ```bash
  rtk uv run pytest tests/test_execution_evidence.py -q
  rtk git check-ignore .forgeagent/execution-artifacts/example/programs/0001-main.py
  ```

  Expected: pytest 全部通过；`git check-ignore` 输出该相对路径；测试目录外没有被写入文件。

- [ ] **Step 6: 提交程序制品 store**

  ```bash
  rtk git add .gitignore src/forgeagent/execution_evidence.py tests/test_execution_evidence.py
  rtk git commit -m "feat: persist generated programs as safe task artifacts"
  ```

### Task 3: 接入 Exec、Step 与 Task 的真实尝试边界

**Files:**
- Modify: `src/forgeagent/tools.py:144-197,344-382`
- Modify: `src/forgeagent/step.py:183-273,506-672`
- Modify: `src/forgeagent/task.py:93-98,101-196,264-348`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_step.py`
- Modify: `tests/test_task.py`
- Modify: `tests/test_m43_executor_rewrite_baseline.py`

**Interfaces:**
- `ToolOutcome` adds `program_artifact: ProgramArtifact | None = None` and `evidence_status: EvidenceStatus | None = None`。
- `ToolContext` adds `program_store: ProgramArtifactStore | None = None`。
- `Step.__init__(..., evidence_recorder: ExecutionEvidenceRecorder | None = None, program_store: ProgramArtifactStore | None = None)` keeps direct callers compatible。
- `TaskOutcome` adds `execution_evidence: ExecutionEvidence = Field(default_factory=ExecutionEvidence)`。
- `Task` owns one recorder and one lazy store rooted at immutable `self._allowed_root`; `Task.close()` closes the store descriptor but retains files。
- `ToolOutcome` validator rejects `success=True` with `artifact_persistence_failed` and rejects persistence-failure outcomes carrying a program artifact。

- [ ] **Step 1: 写 Exec fail-closed 和三 backend RED 测试**

  在 `tests/test_tools.py` 使用 recording backend 与 real `ProgramArtifactStore(tmp_path)` 覆盖 inline 和 named Exec。参数化 trusted、restricted、container recording subclasses，断言 backend 收到的 code 与 artifact bytes 完全一致；backend 返回失败时 `program_artifact` 仍存在；store 抛错时结果为：

  ```python
  assert outcome.success is False
  assert outcome.evidence_status == "artifact_persistence_failed"
  assert outcome.program_artifact is None
  assert backend.calls == []
  assert "tmp_path" not in outcome.detail
  ```

  加一例 Edit 后再次 Exec，断言两个不可变文件内容分别对应版本 1 和版本 2。

- [ ] **Step 2: 写 Step 尝试顺序、跳过和取消 RED 测试**

  在 `tests/test_step.py` 构造 completion registry：第一调用成功且 `completes_task=True`，同一回复后跟第二调用。断言 recorder 只有第一条。再覆盖一成功一失败的顺序、持久化失败状态、dispatch 后设置取消保留既有记录、dispatch 前取消不伪造记录。

  ```python
  assert [(item.tool, item.status) for item in recorder.snapshot().records] == [
      ("First", "succeeded"),
      ("Second", "failed"),
  ]
  ```

- [ ] **Step 3: 写 Task 终态、prose 空证据和模型 path RED 测试**

  在 `tests/test_task.py` 覆盖 completed、failed、refused、needs_info、answered_in_prose、cancelled。直接 prose 必须等于 `ExecutionEvidence()`；有 prior tool 的非完成终态保留记录。解析带 `path="../../outside.py"` 的命名 block 后 Exec，断言 artifact 位于 `tmp_path/.forgeagent/execution-artifacts/...`，`tmp_path.parent / "outside.py"` 不存在。

- [ ] **Step 4: 运行运行时切片并确认 RED**

  ```bash
  rtk uv run pytest tests/test_tools.py tests/test_step.py tests/test_task.py tests/test_m43_executor_rewrite_baseline.py -q
  ```

  Expected: 新字段、program store wiring 和 recorder snapshot 断言失败；既有 filesystem-authority 与 executor baseline 断言不回退。

- [ ] **Step 5: 最小接入 Exec 与 dispatch recorder**

  `ExecTool.run()` 在静态分析之后、`ctx.backend.execute()` 之前执行：

  ```python
  if ctx.program_store is None:
      return ToolOutcome(
          tool="Exec",
          block_name=name,
          success=False,
          detail="program artifact persistence failed",
          evidence_status="artifact_persistence_failed",
      )
  try:
      artifact = ctx.program_store.persist(
          block_name=name,
          language=block.language,
          code=block.code,
      )
  except ProgramArtifactPersistenceError:
      return ToolOutcome(
          tool="Exec",
          block_name=name,
          success=False,
          detail="program artifact persistence failed",
          evidence_status="artifact_persistence_failed",
      )
  result = ctx.backend.execute(block.code, ctx.runtime)
  ```

  成功或 backend 失败返回的 `ToolOutcome` 都携带 `program_artifact=artifact`。`Step._dispatch()` 在获得 `ToolOutcome` 后且返回前恰好调用一次 recorder；缺失 handler 的普通失败也记录。已经完成后被 `_handle_reply()` break 的调用不会进入 `_dispatch()`，因此不会记录。

- [ ] **Step 6: 将 snapshot 放入所有结构化 TaskOutcome**

  `Task.__init__` 创建 `ExecutionEvidenceRecorder()` 与无 I/O 的 `ProgramArtifactStore(self._allowed_root)`，传给 `Step`；`Task.run()` 使用：

  ```python
  outcome = TaskOutcome(
      status=status,
      rounds=rounds,
      memory_results=memory_results,
      execution_evidence=self._evidence_recorder.snapshot(),
  )
  ```

  `Task.close()` 幂等关闭 program store 和 backend，不删除 namespace。保持 task audit 只含既有 bounded counters，不把证据正文复制到 audit。

- [ ] **Step 7: 运行运行时 GREEN 和 focused executor 回归**

  ```bash
  rtk uv run pytest tests/test_tools.py tests/test_step.py tests/test_task.py tests/test_m43_executor_rewrite_baseline.py tests/test_executor.py -q
  ```

  Expected: inline/named/Edit/trusted/restricted/container、prose、失败、取消与 parsed-but-skipped 全部通过；backend 只在 artifact 成功后调用。

- [ ] **Step 8: 提交 Task 运行时接入**

  ```bash
  rtk git add src/forgeagent/tools.py src/forgeagent/step.py src/forgeagent/task.py tests/test_tools.py tests/test_step.py tests/test_task.py tests/test_m43_executor_rewrite_baseline.py
  rtk git commit -m "feat: attach execution evidence to task outcomes"
  ```

### Task 4: 在 CLI 与 REPL 终态只渲染一次本地证据

**Files:**
- Modify: `src/forgeagent/cli.py:167-206,381-465`
- Test: `tests/test_cli.py`
- Test: `tests/test_m41_cli_boundaries.py`

**Interfaces:**
- Produces: `render_execution_evidence(evidence: ExecutionEvidence, console: Console, *, project_root: str | Path | None = None) -> None` in `cli.py`。
- `render_outcome()` calls this renderer once after existing round/stdout rendering。
- REPL remains a consumer of `bindings.run_once()` / `bindings.run_collaboration_once()`；不在 `_cli_repl.py` 增加逐轮打印路径。
- Loop 与 Collaboration 的 report 字段尚未加入，本 Task 只交付 Single/REPL renderer；它们分别在 Task 6/7 接入同一 renderer。

- [ ] **Step 1: 写 Single/REPL 终态汇总 RED 测试**

  在 `tests/test_cli.py` 构造含 Exec artifact 的 `TaskOutcome`，断言输出包含一个 `execution evidence:` 标题、`Exec succeeded` 和本地绝对 `.py` 路径。空 evidence 输出 `execution evidence: no tools or programs executed`。调用 REPL 两次 goal 时每个 Task 各一个终态区块，单个 Task 不因 rounds 数重复标题。

- [ ] **Step 2: 写安全 label、secret 和不安全引用 RED 测试**

  设置已知环境 secret，把它放入 tool/block；断言 terminal capture 不含 secret 或原始控制字符。直接调用共享 renderer 并传入 synthetic traversal、absolute 或 symlink reference，断言 model validation 或 resolver 将其显示为 `program unavailable`，且不显示拼接后的宿主路径。

- [ ] **Step 3: 运行 CLI 测试并确认 RED**

  ```bash
  rtk uv run pytest tests/test_cli.py tests/test_m41_cli_boundaries.py -q
  ```

  Expected: 新 execution-evidence 文本和本地路径断言失败；M41 文件边界基线继续给出真实行数。

- [ ] **Step 4: 实现一个共享终态 renderer**

  renderer 先调用 `public_execution_evidence(..., include_local_paths=True)`；每条只打印 `sequence/tool/status/origin/block`，artifact 路径按以下优先级取得：

  ```python
  path = record.artifact.local_path
  if path is None and project_root is not None:
      path = resolve_local_artifact_path(project_root, record.artifact.reference)
  console.print(f"    program: {path}" if path is not None else "    program unavailable")
  ```

  空 records 且 omitted=0 时打印显式空值；有截断时打印稳定 `omitted=<count>`。保留既有 stdout、失败 detail、memory 和 usage 区域，不把它们复制到证据区。

- [ ] **Step 5: 运行 CLI/REPL GREEN 与文件边界验证**

  ```bash
  rtk uv run pytest tests/test_cli.py tests/test_m41_cli_boundaries.py -q
  ```

  Expected: Single 和 REPL 每 Task 一个终态汇总；纯 prose 显式为空；不安全引用不可用；`cli.py` 与 `_cli_repl.py` 保持 M41 上限内。

- [ ] **Step 6: 提交本地终态投影**

  ```bash
  rtk git add src/forgeagent/cli.py tests/test_cli.py tests/test_m41_cli_boundaries.py
  rtk git commit -m "feat: render terminal execution evidence in local entrypoints"
  ```

### Task 5: 为 HTTP terminal public view 增加安全相对引用

**Files:**
- Modify: `src/forgeagent/http_task_service.py:101-180,583-676`
- Modify: `tests/test_http_task_service.py`
- Modify: `tests/test_http_server.py`
- Modify: `tests/test_http_config.py`

**Interfaces:**
- `TaskRecord.public_view()` only adds `execution_evidence` when `ended_at is not None`。
- Ordinary Task uses `public_execution_evidence(record.outcome.execution_evidence)`；无 outcome 的 terminal failure/cancellation uses `ExecutionEvidence()`。
- JSON shape is `{"records": [...], "truncated": bool, "omitted_count": int}`；artifact contains only `reference`。
- 本 Task 只交付 ordinary Task HTTP 投影；Loop 与 Collaboration HTTP 分支分别随 Task 6/7 的 report 字段接入。`_cli_http.task_factory()` 已把 immutable `settings.allowed_root` 传给 Task，无需修改 assembly。

- [ ] **Step 1: 写 running/terminal/empty HTTP RED 测试**

  在 `tests/test_http_task_service.py` 断言 ordinary running record 没有 `execution_evidence`；completed/stopped/failed/refused/needs-info/cancelled terminal record 有显式 envelope；有 Exec 时 JSON 只含 canonical reference 和 stable status。

- [ ] **Step 2: 写 32 条上限和无泄露 RED 测试**

  构造 40 条证据，把绝对 root、代码、参数、prompt、secret、raw exception marker 放入内部 round/tool 字段。断言 public view 只有前 32 条，`truncated=True`、`omitted_count=8`，整个 `repr(view)` 不含上述 marker 或宿主 root。

  在 `tests/test_http_server.py` 通过现有 authenticated `GET /tasks/<id>` 验证相同 JSON；通过 route 表断言不存在 `/artifacts`、`/execution-artifacts` 下载入口。

- [ ] **Step 3: 写 reference 内部映射与 TTL 保留 RED 测试**

  使用 real `ProgramArtifactStore(tmp_path)` 创建文件，HTTP public view 返回相对 reference；`resolve_local_artifact_path(tmp_path, reference)` 映射到同一 regular file。推进 fake clock 让 TaskRecord 过期后 query 返回既有 not-found，而 artifact bytes 仍存在。

- [ ] **Step 4: 运行 HTTP 测试并确认 RED**

  ```bash
  rtk uv run pytest tests/test_http_task_service.py tests/test_http_server.py tests/test_http_config.py -q
  ```

  Expected: terminal evidence 字段断言失败；既有认证、TTL、unknown task 和 lifecycle 测试保持原行为。

- [ ] **Step 5: 实现 terminal-only public projection**

  在 `TaskRecord.public_view()` 现有 mode-specific counters 完成后统一选择证据：

  ```python
  if self.ended_at is not None:
      source = (
          self.outcome.execution_evidence
          if self.outcome is not None
          else ExecutionEvidence()
      )
      view["execution_evidence"] = public_execution_evidence(source).model_dump(mode="json")
  ```

  该分支限定 `mode == "task"`；aggregate modes 在 Task 6/7 加字段后接入。`_run_record()` 的已有异常 taxonomy 不改，不增加 route、读取函数、TTL 删除或 cleanup hook。

- [ ] **Step 6: 运行 HTTP GREEN 与安全序列化检查**

  ```bash
  rtk uv run pytest tests/test_http_task_service.py tests/test_http_server.py tests/test_http_config.py -q
  ```

  Expected: terminal-only envelope、32 条上限、relative reference、internal mapping、TTL artifact retention 全部通过；认证和 not-found 响应不泄露 identifier。

- [ ] **Step 7: 提交 HTTP 投影**

  ```bash
  rtk git add src/forgeagent/http_task_service.py tests/test_http_task_service.py tests/test_http_server.py tests/test_http_config.py
  rtk git commit -m "feat: expose safe execution evidence over HTTP"
  ```

### Task 6: 在 Loop checkpoint/report 中原子聚合并恢复证据

**Files:**
- Modify: `src/forgeagent/loop.py:188-447,1032-1195,1258-1278`
- Modify: `src/forgeagent/cli.py:543-557,586-851`
- Modify: `src/forgeagent/http_task_service.py:121-180`
- Modify: `tests/test_loop_runner.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_task_service.py`

**Interfaces:**
- `LoopCheckpoint` adds `execution_evidence: ExecutionEvidence = Field(default_factory=ExecutionEvidence)`。
- `LoopReport` adds the same empty-default field and `from_checkpoint()` copies it。
- Single child evidence receives `iteration=current.iterations + 1` before merge。
- Cumulative aggregate evidence uses `dedupe_cumulative_roles=True`；existing `(role, attempt, sequence)` retains its original iteration, unseen records receive current iteration。Task 6 以 aggregate-shaped test double 独立验证该契约，Task 7 再接入真实 `CollaborationReport`。
- `_record_outcome()` writes evidence and child counters in one `LoopCheckpointStore.save()` candidate。
- Terminal `TaskRecord.public_view()` uses `LoopReport.execution_evidence` for mode `loop`; running Loop records still omit terminal evidence。

- [ ] **Step 1: 写 single Loop origin、截断、取消 RED 测试**

  在 `tests/test_loop_runner.py` 给 `_Builder` 返回带证据的 completed/failed/cancelled outcomes。断言终态 report 按 iteration 顺序聚合；预算或取消后保留 prior attempts；从未运行的下一 iteration 不产生记录；超过 32 条使用全局 omitted 计数。

- [ ] **Step 2: 写旧 checkpoint 和中断恢复 RED 测试**

  写入不含 `execution_evidence` 的 v1 JSON，断言 load 为显式空 evidence。运行一轮保存后重新 `LoopRunner.resume()`，第二轮只增加新记录且旧前缀不变。模拟 save 前失败时 counters 与 evidence 都不前进，恢复后不会出现半条记录。

- [ ] **Step 3: 写 nested Collaboration cumulative 去重 RED 测试**

  使用具备 `rounds`、`usage`、`usage_available`、`status`、`stop_reason`、`execution_evidence` 的 aggregate-shaped test double：第一份 report 含 `(generator,1,sequence=1)`；恢复后的累计 report 含原记录和 `(evaluator,1,sequence=1)`。断言 Loop 最终只有两条，generator 保持 iteration 1，evaluator 标为 iteration 2，不把重复 generator 计入 omitted。这样本 Task 不依赖 Task 7 尚未新增的 `CollaborationReport` 字段。

  同时在 `tests/test_http_task_service.py` 断言 terminal Loop 返回同一有界 relative-reference envelope，running Loop 不返回该字段，宿主 absolute root 不出现在 JSON。

- [ ] **Step 4: 运行 Loop 测试并确认 RED**

  ```bash
  rtk uv run pytest tests/test_loop_runner.py tests/test_cli.py tests/test_http_task_service.py -q
  ```

  Expected: checkpoint/report 字段、origin、resume 和 CLI Loop evidence 断言失败；既有预算/attention/status taxonomy 继续通过。

- [ ] **Step 5: 在现有原子 candidate 中加入聚合结果**

  `_record_outcome()` 在计算 rounds/tokens 后先用 `public_execution_evidence()` 去除 child local paths；Single child 按本次 iteration merge，aggregate-shaped child 按 cumulative role key merge。把结果与 iterations/rounds/tokens/failure/attention 放入同一个 `model_copy(update=...)`。不得单独保存证据，也不得在 `_stop()` 伪造记录。

  `LoopReport.from_checkpoint()` 原样复制 durable 安全 evidence；`_render_loop_report(..., project_root=root)` 调用 Task 4 renderer 解析本地路径；`TaskRecord.public_view()` 的 Loop terminal 分支调用 `public_execution_evidence(report.execution_evidence)`，只序列化相对 reference。

- [ ] **Step 6: 运行 Loop GREEN 与 checkpoint 尺寸边界**

  ```bash
  rtk uv run pytest tests/test_loop_runner.py tests/test_cli.py tests/test_http_task_service.py -q
  ```

  Expected: completed/stopped/failed/cancelled、attention stop、v1 load、resume、nested cumulative 去重均通过；最大 32 条证据仍通过既有 256 KiB state-size validator。

- [ ] **Step 7: 提交 Loop durable 聚合**

  ```bash
  rtk git add src/forgeagent/loop.py src/forgeagent/cli.py src/forgeagent/http_task_service.py tests/test_loop_runner.py tests/test_cli.py tests/test_http_task_service.py
  rtk git commit -m "feat: aggregate execution evidence in durable loops"
  ```

### Task 7: 在 Duo/Triad state/report 中按 role 与 attempt 聚合证据

**Files:**
- Modify: `src/forgeagent/collaboration.py:600-760,959-1088,2077-2210,2270-2370,2505-2540`
- Modify: `src/forgeagent/_cli_collaboration.py:44-59,91-179`
- Modify: `src/forgeagent/http_task_service.py:121-180`
- Modify: `tests/test_collaboration_models.py`
- Modify: `tests/test_collaboration_runner.py`
- Modify: `tests/test_collaboration_store.py`
- Modify: `tests/test_collaboration_integrations.py`
- Modify: `tests/test_collaboration_stop_projection.py`
- Modify: `tests/test_http_task_service.py`

**Interfaces:**
- `CollaborationState` and `CollaborationReport` add `execution_evidence: ExecutionEvidence = Field(default_factory=ExecutionEvidence)`；existing acceptance `evidence: tuple[str, ...]` remains unchanged。
- Planner evidence origin is `role="planner", attempt=1`。
- Generator/evaluator successful boundary uses the committed role counter as attempt；failed boundary uses previous counter + 1。
- `_persist_planner_boundary()`, `_persist_role_statistics(role, attempt, outcome)` and `_persist_failed_role_boundary(role, outcome)` save usage, counters where owned, and execution evidence in the same state candidate。
- `CollaborationReport.from_state()` copies bounded execution evidence without role conversation or Task local path。
- Terminal `TaskRecord.public_view()` uses `CollaborationReport.execution_evidence` for mode `duo`/`triad`; running collaboration records still omit terminal evidence。

- [ ] **Step 1: 写 state/report 模型和 v1 兼容 RED 测试**

  在 `tests/test_collaboration_models.py` 断言空默认、role/attempt origin、32 条全局上限和 nested serialization 无 local path。在 `tests/test_collaboration_store.py` 加载不含字段的 v1 state，断言 empty evidence；保存再加载保持完整前缀和 omitted。

- [ ] **Step 2: 写 Duo/Triad role 边界 RED 测试**

  在 `tests/test_collaboration_runner.py` 让 planner、两次 generator、两次 evaluator 各返回不同工具记录；断言确定顺序为 planner → generator 1 → evaluator 1 → generator 2 → evaluator 2。覆盖 invalid submission、needs_info、resource stop、cancelled、role failed，断言已返回 TaskOutcome 的 prior evidence 被保留，未启动 role 不产生记录。

- [ ] **Step 3: 写原子保存、恢复和公开安全 RED 测试**

  模拟 `CollaborationStore.save()` 在 role boundary 失败，断言 attempt/counters/evidence 不出现一半提交。重开 runner 后不重复累计已保存 role。把 code、prompt、raw args、absolute path 和 secret marker 放入内部 outcome，断言 CollaborationReport、HTTP 投影和 CLI 安全 renderer 都不含 marker；terminal Duo/Triad HTTP 只返回 relative reference，running record 不返回 terminal evidence。

- [ ] **Step 4: 运行 collaboration 测试并确认 RED**

  ```bash
  rtk uv run pytest tests/test_collaboration_models.py tests/test_collaboration_runner.py tests/test_collaboration_store.py tests/test_collaboration_integrations.py tests/test_collaboration_stop_projection.py tests/test_http_task_service.py -q
  ```

  Expected: execution evidence 字段、role/attempt、恢复和安全投影断言失败；既有 acceptance evidence、handoff、rejection 与 stop taxonomy 不回退。

- [ ] **Step 5: 将 role evidence 合入现有状态事务**

  在三个 persistence helpers 中调用：

  ```python
  evidence = merge_execution_evidence(
      self._state.execution_evidence,
      public_execution_evidence(outcome.execution_evidence),
      role=role,
      attempt=attempt,
  )
  ```

  结果与 usage、rounds、role counter 写入同一个 candidate。`_validate_state_transition()` 增加 immutable-prefix/omitted monotonic 检查，禁止已有记录被改写或计数回退。`_finish()` 只更新终态字段并保留 state evidence。`render_collaboration_report(..., project_root=root)` 复用 Task 4 renderer；`TaskRecord.public_view()` 的 Duo/Triad terminal 分支序列化 safe report evidence。

- [ ] **Step 6: 运行 Duo/Triad GREEN 与 Loop integration 回归**

  ```bash
  rtk uv run pytest tests/test_collaboration_models.py tests/test_collaboration_runner.py tests/test_collaboration_store.py tests/test_collaboration_integrations.py tests/test_collaboration_stop_projection.py tests/test_loop_runner.py tests/test_cli.py tests/test_http_task_service.py -q
  ```

  Expected: Duo/Triad 所有终态、重试和恢复保留有界证据；acceptance evidence 字段未改名；HTTP 只有相对 reference；CLI 可从可信 project root 显示本地路径。

- [ ] **Step 7: 提交 Collaboration 聚合**

  ```bash
  rtk git add src/forgeagent/collaboration.py src/forgeagent/_cli_collaboration.py src/forgeagent/http_task_service.py tests/test_collaboration_models.py tests/test_collaboration_runner.py tests/test_collaboration_store.py tests/test_collaboration_integrations.py tests/test_collaboration_stop_projection.py tests/test_http_task_service.py
  rtk git commit -m "feat: aggregate execution evidence across collaboration roles"
  ```

### Task 8: 完成端到端矩阵与全量验证

**Files:**
- Modify: `tests/test_execution_evidence.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_server.py`
- Modify: `tests/test_loop_runner.py`
- Modify: `tests/test_collaboration_integrations.py`
- Modify: `openspec/changes/expose-task-execution-evidence/tasks.md`

**Interfaces:**
- End-to-end matrix must cover Single/prose/failure/cancellation, inline/named/Edit Exec, trusted/restricted/container, authenticated HTTP, Loop create/resume, Duo and Triad。
- Every executed program assertion resolves to a real regular `.py` file containing exact selected UTF-8 bytes。
- Every public projection assertion checks both required evidence and prohibited fields。

- [ ] **Step 1: 增加一个离线端到端证据矩阵**

  使用 `MockClient`、recording backends、`tmp_path` 和现有 HTTP test server；禁止 API key 和外网。每种入口同时断言 tool/status/origin/reference，CLI 再断言 local path，HTTP 再断言只有 relative reference。对 prose 明确断言 empty envelope，对取消明确断言 prior-only。

- [ ] **Step 2: 运行新契约与受影响回归集合**

  ```bash
  rtk uv run pytest tests/test_execution_evidence.py tests/test_tools.py tests/test_step.py tests/test_task.py tests/test_cli.py tests/test_http_task_service.py tests/test_http_server.py tests/test_loop_runner.py tests/test_collaboration_models.py tests/test_collaboration_runner.py tests/test_collaboration_store.py tests/test_collaboration_integrations.py tests/test_collaboration_stop_projection.py tests/test_executor.py tests/test_m43_executor_rewrite_baseline.py tests/test_m41_cli_boundaries.py -q
  ```

  Expected: 全部通过，无真实 provider/network 依赖；失败时先按 `systematic-debugging` 定位根因并重跑对应最小测试。

- [ ] **Step 3: 运行格式、静态检查、OpenSpec strict 和全量测试**

  ```bash
  rtk uv run ruff format --check .
  rtk uv run ruff check .
  rtk openspec validate expose-task-execution-evidence --strict
  UV_CACHE_DIR=/tmp/forgeagent-m48-execution-evidence-uv-cache rtk uv run pytest -q
  rtk git diff --check
  ```

  Expected: Ruff format/check 无问题；OpenSpec strict valid；全量 pytest 全绿（existing skips 原样保留）；`git diff --check` 无输出。

- [ ] **Step 4: 做安全边界审查并修复所有 P1/P2**

  审查 diff 时逐项验证：directory descriptor/rebinding、temp cleanup、权限和容量、backend fail-closed、reference canonicalization、local path exclusion、secret/control masking、HTTP 无 route、durable state 32 条上限、Loop cumulative 去重、Collaboration atomic role boundary、旧状态空默认。此处由 Comet 的 `review_mode: thorough` 调度正式 task/final reviewer，不再额外调用另一套 review 命令。任何发现先新增可失败回归测试，再最小修复并重跑 Step 2/3。

- [ ] **Step 5: 做兼容性与遗漏复审**

  对照四份 delta specs 的 8 个 Requirement、35 个 Scenario 建立 test-name 映射，确认 32 条公开上限、128 条内部上限、100/1 MiB/8 MiB 程序上限均有边界两侧测试；确认 `TaskOutcome` 既有字段、Loop/Collaboration schema、HTTP status/reason、CLI stdout/detail/usage 未变。再次执行：

  ```bash
  rtk uv run pytest tests/test_execution_evidence.py tests/test_http_task_service.py tests/test_loop_runner.py tests/test_collaboration_integrations.py -q
  rtk git diff --check
  ```

  Expected: 复审集合全绿，diff check 无输出，spec 的每个 Scenario 均能定位到至少一个测试。

- [ ] **Step 6: 记录 build 完成状态并提交**

  仅在 Step 2-5 全部通过后，把 `openspec/changes/expose-task-execution-evidence/tasks.md` 的 1.3、2.1-2.3、3.1-3.3、4.1-4.2 标记完成，并提交最终测试/清单：

  ```bash
  rtk git add tests/test_execution_evidence.py tests/test_cli.py tests/test_http_server.py tests/test_loop_runner.py tests/test_collaboration_integrations.py openspec/changes/expose-task-execution-evidence/tasks.md
  rtk git commit -m "test: verify task execution evidence end to end"
  ```

  Expected: worktree 只剩 Comet phase transition 产生的受控状态文件变更；源码、测试与任务清单均已提交，未执行 push。

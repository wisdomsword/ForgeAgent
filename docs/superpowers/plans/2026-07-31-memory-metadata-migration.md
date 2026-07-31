---
change: migrate-memory-metadata
design-doc: docs/superpowers/specs/2026-07-31-memory-metadata-migration-design.md
base-ref: 35fe8cce29cdb781fcfcd385c54791c7e1a10795
---

# Memory 元数据迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目级 Memory 升级为宿主拥有治理元数据的单文件 v2，并提供只读 readiness、显式迁移、生命周期治理、语义验证、自动恢复和 revision 冲突保护回滚。

**Architecture:** `MemoryManager` 继续作为唯一权威 API 和项目锁所有者；`MEMORY.md` 使用一个 v2 header 加“元数据 comment + 正文条目”配对，由同一次原子替换提交。旧 v1 只读加载，迁移必须接收完整 manifest，并在锁内依次完成源重验、私有备份、v2 写入、磁盘重读验证和必要时恢复；离线脚本只做参数边界与公开结果 JSON 投影。

**Tech Stack:** Python 3.11 标准库（`dataclasses`、`datetime`、`json`、`secrets`、`fcntl`、`pathlib`）、Pydantic 2.x 现有 `MemoryCandidate`、pytest、Ruff、OpenSpec/Comet。

## Global Constraints

- 仅扩展 project Memory；session Memory 继续只驻留进程内，协议和行为保持兼容。
- `MemoryCandidate` 仍只包含 `scope/kind/key/content`；治理元数据不得进入模型可控制的文本或 native tool 协议。
- 不从 v1 正文推断 `kind`、来源、写入者或真相来源；legacy manifest 必须为每个 key 显式提供 `kind` 和全部治理字段。
- v1 可加载、可渲染，但普通 project 写入必须返回 `rejected/migration_required`，不得自动升级或继续写 v1。
- `_MAX_ENTRIES = 64`、`_MAX_RENDER_BYTES = 32 * 1024` 保持不变；新增 `_MAX_STORAGE_BYTES = 64 * 1024`，分别约束存储和 prompt 投影。
- MEMORY、lock、manifest 和 backup 只能位于指定 project root 内；已有 symlink 或非 regular file/directory 一律拒绝。
- 公开 readiness/operation 结果、CLI JSON、diagnostic、audit 和报告不得包含正文、secret、完整 manifest、key 集、绝对路径或 raw exception。
- 不新增第三方依赖、数据库、向量检索、网络访问、后台调度、自动 TTL、自动 manifest 推断或 force rollback。
- 当前仓库没有 `.forgeagent/MEMORY.md`；只运行 readiness 并记录 `no_data`，不得制造历史数据或执行 migrate。
- 不执行 PyPI、tag、push 或发布自动化。
- 工作区已有大量用户改动。开始前和每次提交前都运行 `git status --short` 与相关文件的 `git diff`；不得 stash、reset、checkout 或覆盖用户改动。
- `src/forgeagent/task.py` 和 `src/forgeagent/cli.py` 已有非 M42 hunks。修改这两个文件时只增加本计划给出的 source 参数 hunk，使用 `git add -p` 选择性暂存，并用 `git diff --cached -- <file>` 证明没有暂存既有 hunk。

---

## File Map

- Modify: `src/forgeagent/memory.py` — v1/v2 格式、治理类型、生命周期、readiness、受控修改、迁移、verify、rollback 和固定审计投影。
- Modify: `src/forgeagent/task.py` — 把模型候选可信入口标记为 `model_candidate`；保留既有 attention hunks。
- Modify: `src/forgeagent/cli.py` — 把 `/remember` 可信入口标记为 `user_command`；保留既有 receipt/CLI hunks。
- Modify: `tests/test_memory.py` — 格式、readiness、元数据所有权、生命周期和受控修改单元测试。
- Create: `tests/test_memory_migration.py` — manifest、备份、迁移、故障恢复、verify 和 rollback 测试。
- Modify: `tests/test_task.py` — Task source 投影与 v1 写入拒绝集成测试；保留既有 attention hunks。
- Modify: `tests/test_cli.py` — `/remember` source 投影与 v1 写入拒绝集成测试；保留既有 CLI hunks。
- Create: `scripts/m42_memory_migration.py` — 离线 readiness/migrate/verify/rollback 入口。
- Create: `tests/test_m42_memory_migration_script.py` — 运维入口边界和最小披露测试。
- Create: `docs/memory-migration.md` — v2、manifest、备份、回滚和人工纠错操作说明。
- Modify: `README.md` — Memory 章节链接到迁移说明；只暂存 M42 hunk。
- Modify: `docs/threat-model.md` — T15 的元数据、备份、失效和回滚控制；只暂存 M42 hunk。
- Modify: `docs/agent-governance-gates.md` — 把 M32 治理问题连接到 M42 运行时 verifier；只暂存 M42 hunk。
- Create: `tests/test_memory_migration_docs.py` — 文档契约测试。
- Modify: `openspec/changes/migrate-memory-metadata/tasks.md` — 实施完成后逐项勾选。
- Create: `docs/superpowers/reports/2026-07-31-memory-metadata-migration-verify.md` — M42 验证证据。
- Create: `milestones/milestone_042.md` — M42 收尾记录。
- Modify: `milestones/latest` — 指向 `milestone_042.md`。

### Task 1: 建立 v2 类型、严格格式与只读 readiness

**Files:**
- Modify: `src/forgeagent/memory.py:5-348`
- Modify: `tests/test_memory.py:1-236`

**Interfaces:**
- Consumes: `MemoryCandidate(scope, kind, key, content)`、现有 project root/path/lock 边界。
- Produces: `MemoryWriteSource`、`MemoryGovernance`、`ProjectMemoryRecord`、`MemoryFileHeader`、`MemoryReadiness`、`MemoryOperationResult`、`MemoryManager.readiness(manifest=None)`，以及严格的 v1/v2 snapshot 解析与 deterministic v2 serializer。

- [ ] **Step 1: 记录基线与重叠文件现状**

  Run:

  ```bash
  git status --short
  git diff -- src/forgeagent/memory.py tests/test_memory.py src/forgeagent/task.py src/forgeagent/cli.py tests/test_task.py tests/test_cli.py
  git rev-parse HEAD
  ```

  Expected: HEAD 为 `35fe8cce29cdb781fcfcd385c54791c7e1a10795`；`memory.py` 和 `test_memory.py` 没有用户 hunk；`task.py`、`cli.py` 及对应测试的既有 hunk保持可见且不被改动。

- [ ] **Step 2: 写 readiness 和格式失败测试**

  在 `tests/test_memory.py` 增加 imports 和精确 fixtures：

  ```python
  import json
  from datetime import UTC, datetime

  from forgeagent.memory import MemoryGovernance, MemoryManager


  def _write_v1(root, entries: dict[str, str]) -> bytes:
      raw = (
          "<!-- forgeagent-memory-v1 -->\n"
          + "".join(f"- {key}: {entries[key]}\n" for key in sorted(entries))
      ).encode("utf-8")
      path = root / ".forgeagent" / "MEMORY.md"
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(raw)
      return raw


  def _legacy_manifest(*keys: str) -> dict[str, dict[str, object]]:
      return {
          key: {
              "kind": "fact",
              "why_remember": "cross_task_fact",
              "source": "legacy_manifest",
              "writer": "unknown",
              "who_can_write": "host_only",
              "truth_source": "unknown",
              "visibility": "project",
              "written_at": "2026-07-31T00:00:00Z",
              "expires_at": None,
              "review_after": "2026-07-31T00:00:00Z",
              "revalidate_on": "conflict_or_explicit_review",
              "recovery": "project_memory_file",
              "delete_or_correct": "host_replace_delete_or_revalidate",
          }
          for key in keys
      }
  ```

  增加以下 tests；现有 v1 malformed-entry test 保留，后续实现仍须满足它：

  ```python
  def test_readiness_no_data_is_read_only_and_minimally_disclosing(tmp_path):
      manager = MemoryManager(str(tmp_path))
      before = tuple(tmp_path.rglob("*"))

      result = manager.readiness()

      assert result.status == "no_data"
      assert result.format_version == "none"
      assert result.entry_count == 0
      assert result.reason == "memory_absent"
      assert tuple(tmp_path.rglob("*")) == before


  def test_readiness_v1_requires_exact_manifest_without_modifying_bytes(tmp_path):
      original = _write_v1(tmp_path, {"editor": "nvim", "language": "python"})
      manager = MemoryManager(str(tmp_path))

      missing = manager.readiness(_legacy_manifest("editor"))
      ready = manager.readiness(_legacy_manifest("editor", "language"))

      assert (missing.status, missing.reason) == (
          "legacy_needs_metadata",
          "manifest_key_mismatch",
      )
      assert (ready.status, ready.format_version, ready.entry_count, ready.reason) == (
          "legacy_ready",
          "v1",
          2,
          "manifest_valid",
      )
      assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
      assert not (tmp_path / ".forgeagent" / "memory-backups").exists()


  @pytest.mark.parametrize(
      ("body", "reason"),
      [
          (b"not-memory\n", "invalid_header"),
          (b"<!-- forgeagent-memory-v1 -->\n- editor: nvim\n- editor: vim\n", "duplicate_key"),
          (b"<!-- forgeagent-memory-v2: {} -->\n", "invalid_header"),
      ],
  )
  def test_readiness_rejects_noncanonical_or_malformed_files(tmp_path, body, reason):
      path = tmp_path / ".forgeagent" / "MEMORY.md"
      path.parent.mkdir()
      path.write_bytes(body)

      result = MemoryManager(str(tmp_path)).readiness()

      assert result.status == "repair_required"
      assert result.reason == reason
      assert str(tmp_path) not in repr(result)
      assert "nvim" not in repr(result)


  def test_readiness_rejects_memory_symlink_without_following_it(tmp_path):
      outside = tmp_path.parent / f"{tmp_path.name}-outside-memory"
      outside.write_text("private-content", encoding="utf-8")
      directory = tmp_path / ".forgeagent"
      directory.mkdir()
      (directory / "MEMORY.md").symlink_to(outside)

      result = MemoryManager(str(tmp_path)).readiness()

      assert (result.status, result.reason) == ("unsafe", "storage_path")
      assert "private-content" not in repr(result)
      assert str(outside) not in repr(result)
  ```

- [ ] **Step 3: 运行 RED 测试**

  Run: `uv run pytest tests/test_memory.py -q`

  Expected: FAIL，首个新失败为无法从 `forgeagent.memory` 导入 `MemoryGovernance` 或 `MemoryManager` 没有 `readiness`。

- [ ] **Step 4: 定义公开类型和固定状态集合**

  在 `src/forgeagent/memory.py` 中增加标准库 imports、常量和以下类型。`ProjectMemoryRecord.governance` 允许 `None` 的唯一原因是 v1 只读兼容；v2 parser 和 verifier 必须拒绝 `None`：

  ```python
  import json
  import secrets
  from collections.abc import Callable, Iterator, Mapping
  from datetime import UTC, datetime
  from typing import Literal, TypeAlias

  MemoryWriteSource: TypeAlias = Literal["host_api", "model_candidate", "user_command"]
  MemoryFormat: TypeAlias = Literal["none", "v1", "v2", "invalid"]
  _MAX_STORAGE_BYTES = 64 * 1024
  _V1_HEADER = "<!-- forgeagent-memory-v1 -->"
  _V2_HEADER_PREFIX = "<!-- forgeagent-memory-v2: "
  _META_PREFIX = "<!-- forgeagent-memory-meta: "
  _OPAQUE_ID = re.compile(r"^[0-9a-f]{32}$")


  @dataclass(frozen=True)
  class MemoryGovernance:
      why_remember: str
      source: str
      writer: str
      who_can_write: str
      truth_source: str
      visibility: str
      written_at: str
      expires_at: str | None
      review_after: str | None
      revalidate_on: str
      recovery: str
      delete_or_correct: str


  @dataclass(frozen=True)
  class ProjectMemoryRecord:
      candidate: MemoryCandidate
      governance: MemoryGovernance | None


  @dataclass(frozen=True)
  class MemoryFileHeader:
      revision: str
      migration_id: str | None = None
      migration_revision: str | None = None


  @dataclass(frozen=True)
  class MemoryReadiness:
      status: Literal[
          "no_data",
          "legacy_needs_metadata",
          "legacy_ready",
          "current",
          "repair_required",
          "unsafe",
      ]
      format_version: Literal["none", "v1", "v2", "unknown"]
      entry_count: int
      reason: str


  @dataclass(frozen=True)
  class MemoryOperationResult:
      status: Literal[
          "migrated",
          "not_required",
          "rejected",
          "persistence_error",
          "recovery_failed",
          "verified",
          "not_current",
          "repair_required",
          "unsafe",
          "rolled_back",
          "rollback_conflict",
          "backup_unavailable",
      ]
      entry_count: int
      reason: str
      migration_id: str | None = None


  @dataclass(frozen=True)
  class _ProjectSnapshot:
      format_version: MemoryFormat
      entries: dict[str, ProjectMemoryRecord]
      header: MemoryFileHeader | None
      raw: bytes | None
      reason: str = ""
  ```

  白名单必须是模块常量；固定治理字段只允许设计中的值，`source` 额外允许迁移专用 `legacy_manifest`，时间戳只允许 UTC 秒精度：

  ```python
  _KINDS = frozenset({"fact", "preference", "decision"})
  _WHY = frozenset({"cross_task_fact", "cross_task_preference", "cross_task_decision"})
  _SOURCES = frozenset({"host_api", "model_candidate", "user_command", "legacy_manifest"})
  _WRITERS = frozenset({"host_api", "task_host", "interactive_host", "unknown"})
  _TRUTH_SOURCES = frozenset(
      {"host_assertion", "model_output_unverified", "user_statement", "unknown"}
  )
  _RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


  def _parse_timestamp(value: str) -> datetime:
      if not _RFC3339_UTC.fullmatch(value):
          raise ValueError("invalid timestamp")
      return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
  ```

- [ ] **Step 5: 实现 bounded snapshot parser、serializer 和 readiness**

  `MemoryManager.__init__` 增加 `clock` 并初始化格式/header/失效诊断状态：

  ```python
  def __init__(
      self,
      allowed_root: str,
      *,
      audit_sink: AuditSink | None = None,
      enabled: bool = True,
      allow_project: bool = True,
      diagnostic: Callable[[str], None] | None = None,
      clock: Callable[[], datetime] | None = None,
  ) -> None:
      self._root = Path(allowed_root).resolve()
      self._path = self._root / ".forgeagent" / "MEMORY.md"
      self._audit_sink = audit_sink
      self._diagnostic = diagnostic
      self._enabled = enabled
      self._allow_project = allow_project
      self._clock = clock or (lambda: datetime.now(UTC))
      self._session: dict[str, MemoryCandidate] = {}
      self._project: dict[str, ProjectMemoryRecord] = {}
      self._project_format: MemoryFormat = "none"
      self._header: MemoryFileHeader | None = None
      self._lifecycle_notices: set[tuple[str, str, str]] = set()
  ```

  实现以下精确私有接口，并让 `load()` 只根据完整 snapshot 更新内存状态：`_read_snapshot(self, *, diagnose: bool = False) -> _ProjectSnapshot`、`_parse_v1(self, raw: bytes, *, canonical: bool) -> _ProjectSnapshot`、`_parse_v2(self, raw: bytes) -> _ProjectSnapshot`、`_parse_governance(self, value: Mapping[str, object]) -> MemoryGovernance`、`_serialize_v2(self, entries: Mapping[str, ProjectMemoryRecord], header: MemoryFileHeader) -> bytes`、`_validate_manifest(self, snapshot: _ProjectSnapshot, manifest: Mapping[str, object] | None) -> tuple[dict[str, ProjectMemoryRecord] | None, str]`。

  这些函数的实现规则是确定的：只用 `json.loads` 解析对象；用 `set(mapping) == expected_fields` 拒绝未知/缺失字段；header 和 metadata 使用 `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`；v2 metadata 的 `kind` 必须与随后的正文 candidate 一致；重复 key、孤立 metadata、额外非空行、无效 UTF-8、无效时间和超过 64 KiB 均返回固定 reason。v1 compatibility load 保持逐条隔离，但 `readiness` 和 `migrate` 使用 `canonical=True` 拒绝畸形行与重复 key。

  `readiness` 必须仅调用只读 snapshot 逻辑：

  ```python
  def readiness(self, manifest: Mapping[str, object] | None = None) -> MemoryReadiness:
      try:
          snapshot = self._read_snapshot()
      except OSError:
          return MemoryReadiness("unsafe", "unknown", 0, "storage_path")
      if snapshot.format_version == "none":
          return MemoryReadiness("no_data", "none", 0, "memory_absent")
      if snapshot.format_version == "invalid":
          return MemoryReadiness(
              "repair_required", "unknown", len(snapshot.entries), snapshot.reason
          )
      if snapshot.format_version == "v2":
          return MemoryReadiness("current", "v2", len(snapshot.entries), "valid_v2")
      records, reason = self._validate_manifest(snapshot, manifest)
      if records is None:
          return MemoryReadiness("legacy_needs_metadata", "v1", len(snapshot.entries), reason)
      return MemoryReadiness("legacy_ready", "v1", len(records), "manifest_valid")
  ```

- [ ] **Step 6: 运行格式与既有 Memory 回归测试**

  Run:

  ```bash
  uv run pytest tests/test_memory.py -q
  uv run ruff check src/forgeagent/memory.py tests/test_memory.py
  ```

  Expected: PASS；既有 v1 load/render、session、symlink、lock 和审计测试仍通过。

- [ ] **Step 7: 提交格式/readiness 基线**

  ```bash
  git add src/forgeagent/memory.py tests/test_memory.py
  git diff --cached --check
  git diff --cached -- src/forgeagent/memory.py tests/test_memory.py
  git commit -m "feat(memory): add v2 readiness contract"
  ```

### Task 2: 用宿主来源生成 v2 元数据并接通 Task/REPL

**Files:**
- Modify: `src/forgeagent/memory.py:116-218`
- Modify: `src/forgeagent/task.py:247-257`
- Modify: `src/forgeagent/cli.py:1150-1169`
- Modify: `tests/test_memory.py`
- Modify: `tests/test_task.py:284-301`
- Modify: `tests/test_cli.py:521-535`

**Interfaces:**
- Consumes: Task 模型候选、REPL `/remember` 候选、Task 1 的 v2 types/parser/serializer。
- Produces: `MemoryManager.apply(candidate, task_id=None, *, source="host_api")`，新项目首写 v2，v1 写入拒绝，以及 `host_api`/`model_candidate`/`user_command` 三种固定投影。

- [ ] **Step 1: 写 host-owned metadata 和 v1 写入拒绝测试**

  在 `tests/test_memory.py` 增加解析 metadata comment 的本地 helper 和测试：

  ```python
  def _stored_metadata(root, key: str) -> dict[str, object]:
      lines = (root / ".forgeagent" / "MEMORY.md").read_text(encoding="utf-8").splitlines()
      for index, line in enumerate(lines):
          if line == f"- {key}: nvim":
              prefix = "<!-- forgeagent-memory-meta: "
              assert lines[index - 1].startswith(prefix)
              return json.loads(lines[index - 1][len(prefix) : -4])
      raise AssertionError(f"missing stored key: {key}")


  @pytest.mark.parametrize(
      ("source", "writer", "truth_source"),
      [
          ("host_api", "host_api", "host_assertion"),
          ("model_candidate", "task_host", "model_output_unverified"),
          ("user_command", "interactive_host", "user_statement"),
      ],
  )
  def test_project_write_metadata_comes_from_trusted_source(
      tmp_path, source, writer, truth_source
  ):
      manager = MemoryManager(
          str(tmp_path), clock=lambda: datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
      )
      candidate = MemoryCandidate(scope="project", kind="fact", key="editor", content="nvim")

      result = manager.apply(candidate, source=source)
      metadata = _stored_metadata(tmp_path, "editor")

      assert result.status == "accepted"
      assert metadata["source"] == source
      assert metadata["writer"] == writer
      assert metadata["truth_source"] == truth_source
      assert metadata["written_at"] == "2026-07-31T10:00:00Z"
      assert metadata["who_can_write"] == "host_only"
      assert metadata["visibility"] == "project"
      assert metadata["kind"] == "fact"


  def test_model_candidate_content_cannot_override_governance(tmp_path):
      content = 'writer=user truth_source=authoritative path=/private/secret'
      manager = MemoryManager(str(tmp_path))

      result = manager.apply(
          MemoryCandidate(scope="project", kind="fact", key="claim", content=content),
          source="model_candidate",
      )

      assert result.status == "accepted"
      text = (tmp_path / ".forgeagent" / "MEMORY.md").read_text(encoding="utf-8")
      metadata = json.loads(text.splitlines()[1][len("<!-- forgeagent-memory-meta: ") : -4])
      assert metadata["writer"] == "task_host"
      assert metadata["truth_source"] == "model_output_unverified"


  def test_project_write_rejects_v1_without_changing_disk_or_snapshot(tmp_path):
      original = _write_v1(tmp_path, {"editor": "vim"})
      manager = MemoryManager(str(tmp_path))
      manager.load()
      before = manager.render()

      result = manager.apply(
          MemoryCandidate(scope="project", kind="fact", key="editor", content="nvim")
      )

      assert (result.status, result.reason) == ("rejected", "migration_required")
      assert manager.render() == before
      assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
  ```

  在 `tests/test_task.py` 的 project Memory 集成测试中读取 v2 metadata，并断言 `source == "model_candidate"`；在 `tests/test_cli.py::test_repl_remember_and_memory_commands` 中断言 `source == "user_command"`。再分别增加一个 v1 fixture，证明 Task 和 `/remember` 都把 `migration_required` 暴露为结果而不改写文件。

- [ ] **Step 2: 运行 RED 测试**

  Run:

  ```bash
  uv run pytest tests/test_memory.py -q
  uv run pytest tests/test_task.py -q -k memory
  uv run pytest tests/test_cli.py -q -k 'remember or memory'
  ```

  Expected: FAIL，因为 `apply` 尚不接受 `source`、首写仍是 v1、Task/REPL 未传递可信来源。

- [ ] **Step 3: 实现固定来源投影与 v2 project write**

  在 `memory.py` 中增加固定投影；`MemoryCandidate` 字段不得参与映射选择：

  ```python
  _SOURCE_PROJECTION = {
      "host_api": ("host_api", "host_assertion"),
      "model_candidate": ("task_host", "model_output_unverified"),
      "user_command": ("interactive_host", "user_statement"),
  }
  _WHY_BY_KIND = {
      "fact": "cross_task_fact",
      "preference": "cross_task_preference",
      "decision": "cross_task_decision",
  }


  def _format_timestamp(value: datetime) -> str:
      if value.tzinfo is None:
          raise ValueError("clock must return an aware datetime")
      return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


  def _governance_for_write(
      self, candidate: MemoryCandidate, source: MemoryWriteSource
  ) -> MemoryGovernance:
      writer, truth_source = _SOURCE_PROJECTION[source]
      return MemoryGovernance(
          why_remember=_WHY_BY_KIND[candidate.kind],
          source=source,
          writer=writer,
          who_can_write="host_only",
          truth_source=truth_source,
          visibility="project",
          written_at=_format_timestamp(self._clock()),
          expires_at=None,
          review_after=None,
          revalidate_on="conflict_or_explicit_review",
          recovery="project_memory_file",
          delete_or_correct="host_replace_delete_or_revalidate",
      )
  ```

  把 project 分支改为锁内读取 snapshot：`none` 创建 v2，`v1` 返回 `migration_required`，`v2` 合并 record，`invalid`/unsafe 映射固定 persistence reason。计算 active render 大小和完整 serializer 存储大小后再 `_atomic_write_bytes`，写后重新解析成功才更新 manager；每次成功写生成 `secrets.token_hex(16)` revision，并保留 header 的 migration fields。

- [ ] **Step 4: 在可信调用点传递 source**

  `src/forgeagent/task.py` 只改这一处调用：

  ```python
  self._memory_manager.apply(
      candidate,
      task_id=self._task_id,
      source="model_candidate",
  )
  ```

  `src/forgeagent/cli.py` 只改 `/remember` 的调用：

  ```python
  outcome = manager.apply(candidate, source="user_command")
  ```

  不修改 `MemoryCandidate`、protocol parser 或 HTTP schema。

- [ ] **Step 5: 运行专项和集成 GREEN 测试**

  Run:

  ```bash
  uv run pytest tests/test_memory.py -q
  uv run pytest tests/test_task.py -q -k memory
  uv run pytest tests/test_cli.py -q -k 'remember or memory'
  uv run pytest tests/test_golden_candidates_memory.py -q
  uv run ruff check src/forgeagent/memory.py src/forgeagent/task.py src/forgeagent/cli.py tests/test_memory.py tests/test_task.py tests/test_cli.py
  ```

  Expected: PASS；golden Memory catalog 仍是一条 accepted、一条 procedure rejected。

- [ ] **Step 6: 选择性暂存并检查脏文件**

  ```bash
  git add src/forgeagent/memory.py tests/test_memory.py
  git add -p src/forgeagent/task.py src/forgeagent/cli.py tests/test_task.py tests/test_cli.py
  git diff --cached -- src/forgeagent/task.py src/forgeagent/cli.py tests/test_task.py tests/test_cli.py
  git diff --cached --check
  ```

  Expected: cached diff 只含两个 `source=` 调用和对应 M42 测试；不得含 attention、receipt_store、HTTP、collaboration 或其他既有 hunks。

- [ ] **Step 7: 提交来源投影**

  Run: `git commit -m "feat(memory): persist host-owned metadata"`

### Task 3: 实现到期过滤、受控纠错、删除与复核

**Files:**
- Modify: `src/forgeagent/memory.py`
- Modify: `tests/test_memory.py`

**Interfaces:**
- Consumes: Task 1 的 `MemoryGovernance`/header/snapshot 和 Task 2 的 v2 project writes。
- Produces: active-only `render()`、`correct_project(candidate, governance, *, task_id=None)`、`delete_project(key, *, task_id=None)`、`revalidate_project(key, *, review_after, expires_at, truth_source, task_id=None)`；每次成功变更生成新 revision。

- [ ] **Step 1: 写 lifecycle RED 测试**

  在 `tests/test_memory.py` 增加：

  ```python
  def _governance(**changes) -> MemoryGovernance:
      values = {
          "why_remember": "cross_task_fact",
          "source": "host_api",
          "writer": "host_api",
          "who_can_write": "host_only",
          "truth_source": "host_assertion",
          "visibility": "project",
          "written_at": "2026-07-31T10:00:00Z",
          "expires_at": None,
          "review_after": None,
          "revalidate_on": "conflict_or_explicit_review",
          "recovery": "project_memory_file",
          "delete_or_correct": "host_replace_delete_or_revalidate",
      }
      values.update(changes)
      return MemoryGovernance(**values)


  def test_render_excludes_expired_and_review_due_records_once_per_revision(tmp_path):
      messages: list[str] = []
      now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
      manager = MemoryManager(str(tmp_path), clock=lambda: now, diagnostic=messages.append)
      candidate = MemoryCandidate(scope="project", kind="fact", key="editor", content="nvim")
      manager.apply(candidate)
      manager.correct_project(
          candidate,
          _governance(review_after="2026-07-31T12:00:00Z"),
      )

      assert "editor" not in manager.render()
      assert "editor" not in manager.render()
      assert messages.count("memory record inactive: review_due") == 1


  def test_correct_delete_and_revalidate_are_atomic_and_change_revision(tmp_path):
      now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
      manager = MemoryManager(str(tmp_path), clock=lambda: now)
      editor = MemoryCandidate(scope="project", kind="fact", key="editor", content="nvim")
      language = MemoryCandidate(scope="project", kind="fact", key="language", content="python")
      manager.apply(editor)
      manager.apply(language)
      before = json.loads(
          (tmp_path / ".forgeagent" / "MEMORY.md").read_text().splitlines()[0][
              len("<!-- forgeagent-memory-v2: ") : -4
          ]
      )["revision"]

      corrected = MemoryCandidate(scope="project", kind="fact", key="editor", content="helix")
      assert manager.correct_project(corrected, _governance()).status == "replaced"
      assert manager.delete_project("language").status == "accepted"
      assert manager.revalidate_project(
          "editor",
          review_after="2026-08-31T00:00:00Z",
          expires_at=None,
          truth_source="host_assertion",
      ).status == "accepted"

      text = (tmp_path / ".forgeagent" / "MEMORY.md").read_text()
      after = json.loads(text.splitlines()[0][len("<!-- forgeagent-memory-v2: ") : -4])[
          "revision"
      ]
      assert after != before
      assert "editor: helix" in manager.render()
      assert "language" not in text
  ```

  再增加参数化测试：`expires_at == now`、`review_after == now` 均不渲染；`None` 日期继续渲染；naive clock、非法时间、错误 key、v1/invalid storage 均固定拒绝；audit/diagnostic repr 不含正文、绝对 root 或底层 exception。

- [ ] **Step 2: 运行 lifecycle RED 测试**

  Run: `uv run pytest tests/test_memory.py -q -k 'expired or review or correct or delete or revalidate'`

  Expected: FAIL，因为三个受控方法和 active-only projection 尚不存在。

- [ ] **Step 3: 实现 active projection 与去重诊断**

  增加以下明确逻辑；v1 records 的 `governance is None` 继续兼容渲染：

  ```python
  def _inactive_reason(self, record: ProjectMemoryRecord) -> str | None:
      governance = record.governance
      if governance is None:
          return None
      now = self._clock()
      if now.tzinfo is None:
          raise ValueError("clock must return an aware datetime")
      if governance.expires_at is not None and now >= _parse_timestamp(governance.expires_at):
          return "expired"
      if governance.review_after is not None and now >= _parse_timestamp(governance.review_after):
          return "review_due"
      return None


  def _active_project(self) -> dict[str, MemoryCandidate]:
      active: dict[str, MemoryCandidate] = {}
      revision = self._header.revision if self._header is not None else "legacy"
      for key, record in self._project.items():
          reason = self._inactive_reason(record)
          if reason is None:
              active[key] = record.candidate
              continue
          notice = (revision, key, reason)
          if notice not in self._lifecycle_notices:
              self._lifecycle_notices.add(notice)
              self._diagnose(f"memory record inactive: {reason}")
              self._audit(reason, "project", record.candidate.kind, key, reason)
      return active
  ```

  `render()` 调用 `_active_project()`；异常只映射固定 `memory record inactive: invalid_time`，不得拼接 exception。

- [ ] **Step 4: 实现共享锁内 read-modify-write 操作**

  增加一个私有 `_mutate_current_v2`，锁内重读当前 v2、应用纯函数、生成新 revision、验证 storage/render 上限、原子写、重读验证后才更新 snapshot。三个 public 方法只能调用该 helper，签名固定为 `correct_project(self, candidate: MemoryCandidate, governance: MemoryGovernance, *, task_id: str | None = None) -> MemoryResult`、`delete_project(self, key: str, *, task_id: str | None = None) -> MemoryResult`、`revalidate_project(self, key: str, *, review_after: str | None, expires_at: str | None, truth_source: str, task_id: str | None = None) -> MemoryResult`。

  `correct_project` 重验 candidate 和完整 governance；`delete_project` 要求合法 key 且存在；`revalidate_project` 只允许白名单 truth source、合法时间，并用 `dataclasses.replace` 保留其余治理字段。成功操作分别发出 `memory.replaced`、`memory.deleted`、`memory.revalidated`，参数只含 scope/kind/key/reason/revision。

- [ ] **Step 5: 运行 GREEN 和回归测试**

  Run:

  ```bash
  uv run pytest tests/test_memory.py -q
  uv run pytest tests/test_task.py tests/test_cli.py tests/test_golden_candidates_memory.py -q -k 'memory or remember'
  uv run ruff check src/forgeagent/memory.py tests/test_memory.py
  ```

  Expected: PASS；session Memory 和 v1 compatible render 不回归。

- [ ] **Step 6: 提交生命周期能力**

  ```bash
  git add src/forgeagent/memory.py tests/test_memory.py
  git diff --cached --check
  git commit -m "feat(memory): enforce lifecycle governance"
  ```

### Task 4: 实现 manifest 迁移、私有备份和磁盘语义 verifier

**Files:**
- Modify: `src/forgeagent/memory.py`
- Create: `tests/test_memory_migration.py`

**Interfaces:**
- Consumes: canonical v1 snapshot、完整 `Mapping[str, object]` manifest、Task 1 的 strict v2 parser。
- Produces: `migrate_legacy(manifest, *, task_id=None)`、`verify_project(*, task_id=None)`、项目内 `.forgeagent/memory-backups/<migration-id>.memory-v1.bak` 和写后语义验证。

- [ ] **Step 1: 写 migration/verify RED 测试与本地 fixture**

  创建 `tests/test_memory_migration.py`：

  ```python
  import json
  import stat
  from datetime import UTC, datetime

  import pytest

  import forgeagent.memory as memory_module
  from forgeagent.memory import MemoryManager


  PRIVATE_VALUE = "migration-private-value"


  def _write_v1(root, entries: dict[str, str]) -> bytes:
      raw = (
          "<!-- forgeagent-memory-v1 -->\n"
          + "".join(f"- {key}: {entries[key]}\n" for key in sorted(entries))
      ).encode()
      path = root / ".forgeagent" / "MEMORY.md"
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(raw)
      return raw


  def _manifest(*keys: str, truth_source: str = "user_statement"):
      return {
          key: {
              "kind": "fact",
              "why_remember": "cross_task_fact",
              "source": "legacy_manifest",
              "writer": "unknown",
              "who_can_write": "host_only",
              "truth_source": truth_source,
              "visibility": "project",
              "written_at": "2026-07-30T00:00:00Z",
              "expires_at": None,
              "review_after": None,
              "revalidate_on": "conflict_or_explicit_review",
              "recovery": "project_memory_file",
              "delete_or_correct": "host_replace_delete_or_revalidate",
          }
          for key in keys
      }


  @pytest.mark.parametrize(
      "manifest",
      [None, _manifest("extra"), {"editor": {"kind": "fact"}}],
  )
  def test_migrate_rejects_incomplete_or_mismatched_manifest_before_backup(tmp_path, manifest):
      original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
      manager = MemoryManager(str(tmp_path))

      result = manager.migrate_legacy(manifest)

      assert (result.status, result.entry_count) == ("rejected", 1)
      assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
      assert not (tmp_path / ".forgeagent" / "memory-backups").exists()
      assert PRIVATE_VALUE not in repr(result)
      assert str(tmp_path) not in repr(result)


  def test_migrate_creates_private_backup_and_verified_semantic_v2(tmp_path):
      original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
      manager = MemoryManager(
          str(tmp_path),
          clock=lambda: datetime(2026, 7, 31, 0, 0, tzinfo=UTC),
      )

      result = manager.migrate_legacy(_manifest("editor"))

      assert (result.status, result.entry_count, result.reason) == ("migrated", 1, "verified")
      assert result.migration_id is not None and len(result.migration_id) == 32
      backup_dir = tmp_path / ".forgeagent" / "memory-backups"
      backup = backup_dir / f"{result.migration_id}.memory-v1.bak"
      assert backup.read_bytes() == original
      assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
      assert stat.S_IMODE(backup.stat().st_mode) == 0o600
      assert manager.verify_project().status == "verified"
      assert PRIVATE_VALUE in manager.render()


  def test_unknown_truth_source_is_preserved_but_immediately_review_due(tmp_path):
      _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
      now = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
      manager = MemoryManager(str(tmp_path), clock=lambda: now)

      result = manager.migrate_legacy(_manifest("editor", truth_source="unknown"))

      assert result.status == "migrated"
      assert PRIVATE_VALUE not in manager.render()
      assert '"review_after":"2026-07-31T00:00:00Z"' in (
          tmp_path / ".forgeagent" / "MEMORY.md"
      ).read_text()
  ```

  再添加测试覆盖：manifest 必须显式 `kind` 且 metadata kind/why 对应；source 只能为 `legacy_manifest`；backup directory/file symlink 拒绝；backup 名已存在不得覆盖；oversize/畸形 v1 在备份前停止；result/audit 不含正文、root、manifest 或 monkeypatch exception 文本。

- [ ] **Step 2: 运行 migration RED 测试**

  Run: `uv run pytest tests/test_memory_migration.py -q`

  Expected: FAIL，因为 `migrate_legacy` 和 `verify_project` 尚不存在。

- [ ] **Step 3: 实现 symlink-safe backup 与迁移事务**

  增加固定私有接口 `_safe_backup_directory(self, *, create: bool) -> Path | None`、`_safe_backup_path(self, migration_id: str) -> Path`、`_create_backup(self, migration_id: str, raw: bytes) -> Path`、`_atomic_write_bytes(self, raw: bytes) -> None` 和 `_verify_migration_snapshot(self, before: _ProjectSnapshot, after: _ProjectSnapshot, migration_id: str, migration_revision: str) -> bool`。

  `_create_backup` 必须使用 `O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`、`0o600`、`fchmod`、flush/fsync；目录拒绝 symlink/非目录并收紧到 `0o700`。`_atomic_write_bytes` 复用当前 mkstemp + fsync + `os.replace`，并显式 `fchmod(0o600)`。

  `migrate_legacy` 的实现顺序必须和设计一致：

  ```python
  def migrate_legacy(
      self,
      manifest: Mapping[str, object] | None,
      *,
      task_id: str | None = None,
  ) -> MemoryOperationResult:
      with self._project_lock():
          before = self._read_snapshot()
          if before.format_version != "v1":
              return self._operation_result("not_required", before, "not_legacy", task_id)
          records, reason = self._validate_manifest(before, manifest)
          if records is None:
              return self._operation_result("rejected", before, reason, task_id)
          migration_id = secrets.token_hex(16)
          revision = secrets.token_hex(16)
          header = MemoryFileHeader(revision, migration_id, revision)
          raw_v2 = self._serialize_v2(records, header)
          round_trip = self._parse_v2(raw_v2)
          if not self._verify_migration_snapshot(
              before, round_trip, migration_id, revision
          ):
              return self._operation_result("rejected", before, "verification_failed", task_id)
          backup = self._create_backup(migration_id, before.raw or b"")
          try:
              self._atomic_write_bytes(raw_v2)
              after = self._read_snapshot()
              if not self._verify_migration_snapshot(
                  before, after, migration_id, revision
              ):
                  raise _MigrationVerificationError
          except _MigrationVerificationError:
              return self._restore_after_failed_migration(before, backup, migration_id, task_id)
          except OSError:
              return self._operation_result(
                  "persistence_error", before, "migration_write_failed", task_id
              )
          self._install_snapshot(after)
          return self._operation_result("migrated", after, "verified", task_id)
  ```

  实际实现必须把 backup 创建后但 replace 前的 OSError 映射为固定失败，并保留原 v1；不能在 public result 中保留 `backup` Path。unknown truth source 的 `review_after` 用 `min(existing_review_after, migration_now)` 规范为不晚于当前注入时钟。

- [ ] **Step 4: 实现只读 verify**

  ```python
  def verify_project(self, *, task_id: str | None = None) -> MemoryOperationResult:
      try:
          snapshot = self._read_snapshot()
      except OSError:
          return MemoryOperationResult("unsafe", 0, "storage_path")
      if snapshot.format_version == "none":
          return MemoryOperationResult("not_current", 0, "memory_absent")
      if snapshot.format_version == "v1":
          return MemoryOperationResult("not_current", len(snapshot.entries), "legacy_format")
      if snapshot.format_version != "v2" or snapshot.header is None:
          return MemoryOperationResult(
              "repair_required", len(snapshot.entries), snapshot.reason or "invalid_format"
          )
      return MemoryOperationResult(
          "verified",
          len(snapshot.entries),
          "valid_v2",
          snapshot.header.migration_id,
      )
  ```

  verify 不获取写锁、不创建目录、不修改文件；审计只包含 operation/status/reason/entry_count 和 opaque id/revision。

- [ ] **Step 5: 运行 GREEN、权限和脱敏测试**

  Run:

  ```bash
  uv run pytest tests/test_memory_migration.py -q
  uv run pytest tests/test_memory.py -q
  uv run ruff check src/forgeagent/memory.py tests/test_memory_migration.py
  ```

  Expected: PASS；成功迁移可 reload/render/verify，所有 pre-write 失败保留原 bytes。

- [ ] **Step 6: 提交迁移和 verifier**

  ```bash
  git add src/forgeagent/memory.py tests/test_memory_migration.py
  git diff --cached --check
  git commit -m "feat(memory): add verified legacy migration"
  ```

### Task 5: 实现写后自动恢复与 revision 绑定 rollback

**Files:**
- Modify: `src/forgeagent/memory.py`
- Modify: `tests/test_memory_migration.py`

**Interfaces:**
- Consumes: Task 4 的 backup、迁移 header 和 `_atomic_write_bytes`。
- Produces: 写后验证失败自动恢复、`rollback_migration(migration_id, *, task_id=None)`、后续 revision 冲突拒绝和无 force 路径。

- [ ] **Step 1: 写恢复/rollback RED 测试**

  在 `tests/test_memory_migration.py` 增加：

  ```python
  def test_post_write_verification_failure_restores_exact_v1_bytes(tmp_path, monkeypatch):
      original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
      manager = MemoryManager(str(tmp_path))
      real_verify = manager._verify_migration_snapshot
      calls = 0

      def fail_disk_verification(before, after, migration_id, migration_revision):
          nonlocal calls
          calls += 1
          if calls == 2:
              return False
          return real_verify(before, after, migration_id, migration_revision)

      monkeypatch.setattr(manager, "_verify_migration_snapshot", fail_disk_verification)

      result = manager.migrate_legacy(_manifest("editor"))

      assert (result.status, result.reason) == ("persistence_error", "verification_failed")
      assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original
      assert PRIVATE_VALUE not in repr(result)


  def test_failed_restore_reports_unknown_without_claiming_success(tmp_path, monkeypatch):
      _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
      manager = MemoryManager(str(tmp_path))
      real_write = manager._atomic_write_bytes
      writes = 0

      def corrupt_then_fail_restore(raw):
          nonlocal writes
          writes += 1
          if writes == 1:
              real_write(b"corrupt-after-replace\n")
              return
          raise OSError("private restore failure")

      monkeypatch.setattr(manager, "_atomic_write_bytes", corrupt_then_fail_restore)

      result = manager.migrate_legacy(_manifest("editor"))

      assert (result.status, result.reason) == ("recovery_failed", "restore_unconfirmed")
      assert "private restore failure" not in repr(result)
      assert PRIVATE_VALUE not in repr(result)


  def test_rollback_restores_unchanged_migration_but_rejects_later_revision(tmp_path):
      original = _write_v1(tmp_path, {"editor": PRIVATE_VALUE})
      manager = MemoryManager(str(tmp_path))
      migrated = manager.migrate_legacy(_manifest("editor"))
      assert migrated.migration_id is not None

      rolled_back = manager.rollback_migration(migrated.migration_id)

      assert (rolled_back.status, rolled_back.reason) == ("rolled_back", "verified_v1")
      assert (tmp_path / ".forgeagent" / "MEMORY.md").read_bytes() == original

      migrated_again = manager.migrate_legacy(_manifest("editor"))
      manager.apply(
          memory_module.MemoryCandidate(
              scope="project", kind="fact", key="language", content="python"
          )
      )

      conflict = manager.rollback_migration(migrated_again.migration_id or "")

      assert (conflict.status, conflict.reason) == (
          "rollback_conflict",
          "revision_changed",
      )
      assert "language: python" in manager.render()
  ```

  再增加测试覆盖：id 不是 32 位小写 hex、id 不匹配 header、backup 缺失、backup symlink、backup mode 不是 `0600`、backup 不是 canonical v1、恢复后重读失败；所有分支不得暴露路径/正文/exception；inspect signature 证明没有 `force` 参数。

- [ ] **Step 2: 运行恢复/rollback RED 测试**

  Run: `uv run pytest tests/test_memory_migration.py -q -k 'restore or rollback or post_write'`

  Expected: FAIL，因为恢复 helper 和 `rollback_migration` 尚未满足契约。

- [ ] **Step 3: 实现自动恢复的确认语义**

  `_restore_after_failed_migration` 必须使用 backup 原 bytes 调 `_atomic_write_bytes`，再重读并同时证明字节相等、canonical v1 parse 和 entry_count 相等；只有三项均成立才返回 `persistence_error/verification_failed`，否则返回 `recovery_failed/restore_unconfirmed`，且不把 manager snapshot 安装成成功 v2。

  ```python
  def _restore_after_failed_migration(
      self,
      before: _ProjectSnapshot,
      backup: Path,
      migration_id: str,
      task_id: str | None,
  ) -> MemoryOperationResult:
      try:
          backup_raw = self._read_safe_backup(backup)
          self._atomic_write_bytes(backup_raw)
          restored = self._read_snapshot()
      except OSError:
          return MemoryOperationResult(
              "recovery_failed", len(before.entries), "restore_unconfirmed", migration_id
          )
      if (
          restored.format_version != "v1"
          or restored.raw != before.raw
          or set(restored.entries) != set(before.entries)
      ):
          return MemoryOperationResult(
              "recovery_failed", len(before.entries), "restore_unconfirmed", migration_id
          )
      self._install_snapshot(restored)
      return MemoryOperationResult(
          "persistence_error", len(before.entries), "verification_failed", migration_id
      )
  ```

- [ ] **Step 4: 实现 revision 绑定 rollback**

  ```python
  def rollback_migration(
      self,
      migration_id: str,
      *,
      task_id: str | None = None,
  ) -> MemoryOperationResult:
      if not _OPAQUE_ID.fullmatch(migration_id):
          return MemoryOperationResult("backup_unavailable", 0, "invalid_migration_id")
      try:
          with self._project_lock():
              current = self._read_snapshot()
              header = current.header
              if current.format_version != "v2" or header is None:
                  return self._operation_result("not_current", current, "not_current", task_id)
              if header.migration_id != migration_id:
                  return self._operation_result(
                      "rollback_conflict", current, "migration_id_mismatch", task_id
                  )
              if header.revision != header.migration_revision:
                  return self._operation_result(
                      "rollback_conflict", current, "revision_changed", task_id
                  )
              backup_raw = self._read_safe_backup(self._safe_backup_path(migration_id))
              backup_snapshot = self._parse_v1(backup_raw, canonical=True)
              if backup_snapshot.format_version != "v1":
                  return self._operation_result(
                      "backup_unavailable", current, "invalid_backup", task_id
                  )
              self._atomic_write_bytes(backup_raw)
              restored = self._read_snapshot()
              if restored.format_version != "v1" or restored.raw != backup_raw:
                  return self._operation_result(
                      "recovery_failed", restored, "restore_unconfirmed", task_id
                  )
              self._install_snapshot(restored)
              return self._operation_result(
                  "rolled_back", restored, "verified_v1", task_id, migration_id
              )
      except OSError:
          return MemoryOperationResult("backup_unavailable", 0, "backup_unavailable")
  ```

  `_read_safe_backup` 必须以 `O_RDONLY | O_NOFOLLOW | O_CLOEXEC` 打开，`fstat` 同时验证 regular file、`0600` 和 `<= _MAX_STORAGE_BYTES`，不得通过 Path 先跟随 symlink。

- [ ] **Step 5: 运行故障矩阵和全 Memory 测试**

  Run:

  ```bash
  uv run pytest tests/test_memory_migration.py -q
  uv run pytest tests/test_memory.py tests/test_task.py tests/test_cli.py tests/test_golden_candidates_memory.py -q -k 'memory or remember or rollback'
  uv run ruff check src/forgeagent/memory.py tests/test_memory_migration.py
  ```

  Expected: PASS；rollback 冲突时当前 v2 bytes 不变；所有 recovery_failed 分支保留 backup 且不宣称成功。

- [ ] **Step 6: 提交恢复和回滚**

  ```bash
  git add src/forgeagent/memory.py tests/test_memory_migration.py
  git diff --cached --check
  git commit -m "feat(memory): add conflict-safe rollback"
  ```

### Task 6: 增加离线运维入口并验证当前仓库 no-data

**Files:**
- Create: `scripts/m42_memory_migration.py`
- Create: `tests/test_m42_memory_migration_script.py`

**Interfaces:**
- Consumes: `MemoryManager.readiness/migrate_legacy/verify_project/rollback_migration`。
- Produces: `readiness`、`migrate`、`verify`、`rollback` 四个离线子命令，单行公开 JSON，确定性退出码；manifest 只能是 project-relative safe regular JSON。

- [ ] **Step 1: 写脚本 RED 测试**

  创建 `tests/test_m42_memory_migration_script.py`：

  ```python
  import json
  import os
  import subprocess
  import sys
  from pathlib import Path


  ROOT = Path(__file__).parents[1]
  SCRIPT = ROOT / "scripts" / "m42_memory_migration.py"


  def _run(*args: str):
      environment = dict(os.environ)
      environment["PYTHONPATH"] = str(ROOT / "src")
      return subprocess.run(
          [sys.executable, str(SCRIPT), *args],
          cwd=ROOT,
          env=environment,
          text=True,
          capture_output=True,
          check=False,
      )


  def test_readiness_no_data_is_single_line_json_and_does_not_write(tmp_path):
      result = _run("readiness", "--root", str(tmp_path))

      assert result.returncode == 0
      assert result.stderr == ""
      assert json.loads(result.stdout) == {
          "entry_count": 0,
          "format_version": "none",
          "reason": "memory_absent",
          "status": "no_data",
      }
      assert result.stdout.count("\n") == 1
      assert not (tmp_path / ".forgeagent").exists()


  def test_manifest_must_be_project_relative_regular_json(tmp_path):
      outside = tmp_path.parent / f"{tmp_path.name}-manifest.json"
      outside.write_text('{"private":"value"}', encoding="utf-8")

      result = _run(
          "migrate",
          "--root",
          str(tmp_path),
          "--manifest",
          str(outside),
      )

      assert result.returncode == 2
      payload = json.loads(result.stdout)
      assert payload == {"entry_count": 0, "reason": "manifest_path", "status": "rejected"}
      assert str(outside) not in result.stdout
      assert "private" not in result.stdout
  ```

  再添加 tests：manifest symlink、invalid JSON、oversize JSON、verify v1、rollback invalid id、故障 exception；所有 stdout/stderr 不含 fixture 正文、secret、root 或 raw exception。

- [ ] **Step 2: 运行脚本 RED 测试**

  Run: `uv run pytest tests/test_m42_memory_migration_script.py -q`

  Expected: FAIL，因为脚本不存在。

- [ ] **Step 3: 实现窄脚本入口**

  创建 `scripts/m42_memory_migration.py`，实现以下结构；错误结果使用固定字典，不序列化 exception：

  ```python
  from __future__ import annotations

  import argparse
  import json
  import os
  import stat
  from dataclasses import asdict
  from pathlib import Path
  from typing import Sequence

  from forgeagent.memory import MemoryManager

  _MAX_MANIFEST_BYTES = 64 * 1024


  def _load_manifest(root: Path, relative_name: str) -> dict[str, object]:
      relative = Path(relative_name)
      if relative.is_absolute() or ".." in relative.parts:
          raise ValueError("manifest_path")
      candidate = root / relative
      descriptor = os.open(
          candidate,
          os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
      )
      try:
          info = os.fstat(descriptor)
          if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_MANIFEST_BYTES:
              raise ValueError("manifest_file")
          raw = os.read(descriptor, _MAX_MANIFEST_BYTES + 1)
      finally:
          os.close(descriptor)
      value = json.loads(raw.decode("utf-8"))
      if not isinstance(value, dict):
          raise ValueError("manifest_format")
      return value


  def build_parser() -> argparse.ArgumentParser:
      parser = argparse.ArgumentParser(prog="m42-memory-migration")
      subparsers = parser.add_subparsers(dest="command", required=True)
      for name in ("readiness", "verify"):
          command = subparsers.add_parser(name)
          command.add_argument("--root", required=True)
      migrate = subparsers.add_parser("migrate")
      migrate.add_argument("--root", required=True)
      migrate.add_argument("--manifest", required=True)
      rollback = subparsers.add_parser("rollback")
      rollback.add_argument("--root", required=True)
      rollback.add_argument("--migration-id", required=True)
      return parser


  def main(argv: Sequence[str] | None = None) -> int:
      args = build_parser().parse_args(argv)
      root = Path(args.root).resolve()
      manager = MemoryManager(str(root))
      try:
          if args.command == "readiness":
              result = manager.readiness()
          elif args.command == "verify":
              result = manager.verify_project()
          elif args.command == "migrate":
              manifest = _load_manifest(root, args.manifest)
              result = manager.migrate_legacy(manifest)
          else:
              result = manager.rollback_migration(args.migration_id)
      except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
          print(json.dumps({"entry_count": 0, "reason": "manifest_path", "status": "rejected"}, sort_keys=True))
          return 2
      print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
      return 0 if result.status in {"no_data", "legacy_ready", "current", "verified", "migrated", "not_required", "rolled_back"} else 2


  if __name__ == "__main__":
      raise SystemExit(main())
  ```

  实现时把 JSON decode 与 path/file 错误分别映射为 `manifest_format`、`manifest_path`、`manifest_file`；示例 except 的单一 reason 只作为控制结构，不得抹平测试要求的固定分类。

- [ ] **Step 4: 运行脚本 GREEN 与真实仓库 readiness**

  Run:

  ```bash
  uv run pytest tests/test_m42_memory_migration_script.py -q
  uv run python scripts/m42_memory_migration.py readiness --root .
  find .forgeagent -maxdepth 2 -type f -print | sort
  ```

  Expected: pytest PASS；真实命令单行输出 `{"entry_count":0,"format_version":"none","reason":"memory_absent","status":"no_data"}`；文件清单与执行前一致，没有 `MEMORY.md` 或 `memory-backups/`。

- [ ] **Step 5: 提交离线入口**

  ```bash
  git add scripts/m42_memory_migration.py tests/test_m42_memory_migration_script.py
  git diff --cached --check
  git commit -m "feat(memory): add offline migration verifier"
  ```

### Task 7: 更新 Memory 运维、威胁模型和治理文档

**Files:**
- Create: `docs/memory-migration.md`
- Modify: `README.md`
- Modify: `docs/threat-model.md`
- Modify: `docs/agent-governance-gates.md`
- Create: `tests/test_memory_migration_docs.py`

**Interfaces:**
- Consumes: M42 public statuses、脚本命令、v1/v2、backup/rollback 契约。
- Produces: 单一运维说明及 README、威胁模型、治理入口的可执行引用契约。

- [ ] **Step 1: 写文档 RED 测试**

  创建 `tests/test_memory_migration_docs.py`：

  ```python
  from pathlib import Path


  ROOT = Path(__file__).parents[1]


  def test_memory_migration_runbook_covers_bounded_operations():
      text = (ROOT / "docs" / "memory-migration.md").read_text(encoding="utf-8")
      for required in (
          "readiness --root",
          "migrate --root",
          "verify --root",
          "rollback --root",
          "legacy_needs_metadata",
          "migration_required",
          "rollback_conflict",
          ".forgeagent/memory-backups/",
          "0600",
          "不推断",
          "不进入 prompt",
      ):
          assert required in text, required


  def test_memory_migration_is_linked_from_project_governance():
      for relative in ("README.md", "docs/threat-model.md", "docs/agent-governance-gates.md"):
          text = (ROOT / relative).read_text(encoding="utf-8")
          assert "docs/memory-migration.md" in text, relative
          assert "M42" in text, relative
  ```

- [ ] **Step 2: 运行文档 RED 测试**

  Run: `uv run pytest tests/test_memory_migration_docs.py -q`

  Expected: FAIL，因为 runbook 和引用尚不存在。

- [ ] **Step 3: 写具体运维说明**

  `docs/memory-migration.md` 必须按以下固定顺序写完整章节：

  ```markdown
  # Project Memory v2 与迁移

  ## 边界
  ## v2 记录与宿主元数据
  ## Readiness 决策表
  ## Legacy manifest 责任
  ## 显式迁移与 0600 恢复副本
  ## Verify 与 revision 绑定 rollback
  ## 到期、复核、纠错和删除
  ## 人工编辑边界
  ## 离线命令
  ## 当前仓库 M42 证据
  ```

  Readiness 决策表逐行定义 `no_data`、`legacy_needs_metadata`、`legacy_ready`、`current`、`repair_required`、`unsafe` 的后续动作；manifest 表列出 `kind` 和全部十二个治理字段；明确 unknown truth source 立即待复核且不进入 prompt；明确 backup 不自动删除、rollback 无 force、revision 变化返回 `rollback_conflict`。离线命令只使用相对 manifest：

  ```bash
  uv run python scripts/m42_memory_migration.py readiness --root /absolute/project
  uv run python scripts/m42_memory_migration.py migrate --root /absolute/project --manifest .forgeagent/memory-manifest.json
  uv run python scripts/m42_memory_migration.py verify --root /absolute/project
  uv run python scripts/m42_memory_migration.py rollback --root /absolute/project --migration-id 0123456789abcdef0123456789abcdef
  ```

- [ ] **Step 4: 更新三个入口而不覆盖用户 hunks**

  - README Memory 小节增加 `[Project Memory v2 与迁移](docs/memory-migration.md)`，说明 v1 只读和新写入需先迁移。
  - `docs/threat-model.md` T15 增加 host-owned metadata、inactive prompt exclusion、private backup、revision conflict 和残余风险“错误但未到复核期的 host assertion 仍可能被使用”。
  - `docs/agent-governance-gates.md` Memory 四问下增加 M42 verifier 链接，明确治理模板不替代运行时 metadata 校验。

- [ ] **Step 5: 运行文档 GREEN 测试**

  Run:

  ```bash
  uv run pytest tests/test_memory_migration_docs.py tests/test_governance_docs.py -q
  uv run ruff check tests/test_memory_migration_docs.py
  ```

  Expected: PASS。

- [ ] **Step 6: 选择性暂存文档并提交**

  ```bash
  git add docs/memory-migration.md tests/test_memory_migration_docs.py
  git add -p README.md docs/threat-model.md docs/agent-governance-gates.md
  git diff --cached -- README.md docs/threat-model.md docs/agent-governance-gates.md
  git diff --cached --check
  git commit -m "docs(memory): document migration operations"
  ```

  Expected: cached diff 只含 M42 链接与 Memory 治理条款；不含发布退役、HTTP、M41 或其他用户既有文档 hunk。

### Task 8: 完成全量验证、两轮自评和 M42 收尾

**Files:**
- Modify: `openspec/changes/migrate-memory-metadata/tasks.md`
- Create: `docs/superpowers/reports/2026-07-31-memory-metadata-migration-verify.md`
- Create: `milestones/milestone_042.md`
- Modify: `milestones/latest`

**Interfaces:**
- Consumes: Tasks 1-7 的实现、测试、当前仓库 readiness 输出和 Comet 状态。
- Produces: 完整验证证据、已完成任务 ledger、归档 change 和 M42 续接指引。

- [ ] **Step 1: 运行专项与相关集成门禁**

  ```bash
  uv run pytest tests/test_memory.py tests/test_memory_migration.py tests/test_m42_memory_migration_script.py tests/test_memory_migration_docs.py tests/test_task.py tests/test_cli.py tests/test_golden_candidates_memory.py -q
  uv run python scripts/m42_memory_migration.py readiness --root .
  ```

  Expected: tests 全部 PASS；readiness 精确为 `no_data`、零条目；没有创建 `.forgeagent/MEMORY.md` 或 `.forgeagent/memory-backups/`。

- [ ] **Step 2: 运行全量质量门禁**

  ```bash
  uv run pytest
  uv run ruff check .
  uv run ruff format --check .
  openspec validate --all --strict --no-interactive
  git diff --check
  ```

  Expected: 全部 exit 0。记录 pytest 的精确 passed/skipped 数和 OpenSpec 的精确通过数；若失败来自用户既有未暂存 hunk，保留原输出并隔离判断，不修改无关文件。

- [ ] **Step 3: 做第一轮代码/契约自评**

  逐项核对 delta spec 五个 requirements 和全部 scenarios，并用以下搜索确认没有遗漏：

  ```bash
  rg -n "MemoryCandidate|MemoryGovernance|readiness|migrate_legacy|verify_project|rollback_migration|correct_project|delete_project|revalidate_project" src tests scripts docs
  rg -n "force|raw exception|absolute path|manifest|memory-backups" src/forgeagent/memory.py scripts/m42_memory_migration.py docs/memory-migration.md
  ```

  必须确认：legacy manifest 显式提供 `kind`；unknown truth 不注入；v1 只读；readiness 零写；source/truth_source 分离；storage/render 双上限；backup O_EXCL/O_NOFOLLOW/0600；写后失败恢复；rollback revision 冲突；没有 force、正文/path/exception 泄漏。发现问题立即补失败测试、最小修复并重跑受影响测试。

- [ ] **Step 4: 做第二轮敌手/故障自评**

  从 TOCTOU、symlink、跨进程 stale manager、文件在 readiness 后改变、migration 后写入、invalid clock、unknown JSON 字段、重复 key、oversize、恢复再次失败和 audit sink 失败角度重新审查。特别确认 migration 在同一个 project lock 内重读源文件，不能依赖之前 readiness 的快照；失败时不把内存状态安装成成功状态。发现问题立即以 RED/GREEN 循环修复并重复 Step 1-2。

- [ ] **Step 5: 检查公开面没有敏感信息**

  ```bash
  uv run pytest tests/test_memory.py tests/test_memory_migration.py tests/test_m42_memory_migration_script.py -q -k 'disclos or secret or path or exception or audit or diagnostic'
  rg -n "str\(exc\)|repr\(exc\)|str\(self\._path\)|content.*reason|manifest.*parameters" src/forgeagent/memory.py scripts/m42_memory_migration.py
  ```

  Expected: tests PASS；搜索结果为空或仅出现在明确不进入公开对象的内部控制流，逐项在 verification report 说明。

- [ ] **Step 6: 更新任务 ledger 和验证报告**

  将 `openspec/changes/migrate-memory-metadata/tasks.md` 仅在相应 evidence 已取得后从 `- [ ]` 改为 `- [x]`。验证报告按“范围、base-ref、专项验证、全量门禁、真实 readiness、迁移决策、两轮自评、敏感信息检查、未执行动作、剩余风险”顺序写入；所有命令记录实际 exit code 和精确计数，明确 `migration_skipped` 的原因是当前仓库 `no_data`，而不是迁移功能未实现。

- [ ] **Step 7: 通过 Comet verify 并归档**

  Run:

  ```bash
  comet status --json
  openspec validate migrate-memory-metadata --strict --no-interactive
  ```

  按当前 `.comet.yaml` 阶段调用 `comet-verify`，验证通过后调用 `comet-archive`；用户已对本里程碑的推荐决策和收尾给予预授权，但仍需把自动选择归档记录在报告中。归档后运行：

  ```bash
  openspec validate --all --strict --no-interactive
  git status --short
  ```

- [ ] **Step 8: 创建 M42 里程碑并更新 latest**

  `milestones/milestone_042.md` 严格使用 `MILESTONE_GUIDE.md` 模板，写明：v2 contract、readiness、来源投影、lifecycle、migration/verify/rollback、真实 `no_data`、全量验证、两轮自评、PyPI/tag/push 未执行，以及下一阶段只在真实长期 Memory 使用证据出现后规划检索/排序或备份保留策略。将 `milestones/latest` 的唯一内容改为：

  ```text
  milestone_042.md
  ```

- [ ] **Step 9: 选择性提交收尾文件**

  ```bash
  git add openspec/changes/archive/2026-07-31-migrate-memory-metadata docs/superpowers/reports/2026-07-31-memory-metadata-migration-verify.md milestones/milestone_042.md milestones/latest
  git add -p openspec/specs/runtime-memory/spec.md
  git diff --cached --check
  git diff --cached --stat
  git commit -m "docs(memory): close M42 migration milestone"
  git status --short
  ```

  Expected: commit 只含 M42 archive/spec/report/milestone；用户所有无关 modified/untracked 文件仍保持原状态。不要 push、tag、build package 或上传 PyPI。

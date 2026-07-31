# CLI boundary extraction 验证报告

- 变更：`extract-cli-boundaries`
- 里程碑：M41
- 日期：2026-07-31
- 验证模式：full
- 基线提交：`a2c9925f471cd76a0411befd1902793786258595`

## 结论

M41 符合四个内部边界、兼容门面和六项 Rewrite/Dependency 门禁。`forgeagent.cli` 继续作为 console entry point 与历史 monkeypatch 面；拆出的模块不反向导入 `forgeagent.cli`，不拥有领域状态，也未新增运行时依赖。所有硬阈值满足，未触发停止和回退规则。

## Verification Report: extract-cli-boundaries

| Dimension | Status |
| --- | --- |
| Completeness | 9/9 tasks；4/4 requirements 有实现证据 |
| Correctness | 8/8 scenarios 有代码与测试覆盖 |
| Coherence | 遵循四模块、单向依赖、兼容 façade 设计 |

### Issues by Priority

- CRITICAL：无。
- WARNING：无。
- SUGGESTION：无。当前 `cli.py` 为 1789 行，距离 1800 行硬阈值仅余 11 行；后续新增 CLI 职责应进入既有边界，不能回填主模块。

最终判断：All checks passed. Ready for archive.

## 需求与场景映射

- 六项量化门禁：`docs/evaluation/m41/rewrite-dependency-baseline.md` 记录基线、阈值、终值与原始性能样本；结构门禁由 `tests/test_m41_cli_boundaries.py:69` 执行。
- 四个内部边界：`src/forgeagent/_cli_parser.py:27`、`src/forgeagent/_cli_collaboration.py:36`、`src/forgeagent/_cli_repl.py:99`、`src/forgeagent/_cli_http.py:64`；AST 测试禁止反向导入。
- 兼容门面：`src/forgeagent/cli.py:134`、`src/forgeagent/cli.py:1211`、`src/forgeagent/cli.py:1399` 在每次调用时解析当前绑定；`tests/test_m41_cli_boundaries.py:97` 与 `:120` 锁住动态 monkeypatch 契约。
- 输出与 HTTP 行为：7 组帮助哈希由 `tests/test_m41_cli_boundaries.py:178` 校验，CLI/HTTP/Loop/Collaboration 聚焦回归共 483 项通过。
- 有界可回退迁移：四个边界按顺序独立提交；运行时直接依赖仍为 8；没有配置、schema 或数据迁移。

## 两轮自评与修正

- 第一轮逐调用检查 façade、bindings 和资源所有权，发现 `build_real_client` 的直接 alias 不再使用当前 `cli.load_registry`，以及 `_StartupDisplay` 绕过当前门面的启动能力判断；已改为薄 wrapper 和显式 callback，并补失败优先回归。
- 第二轮检查模块归属、依赖方向、阈值和工作区隔离，发现两段环境配置解析仍留在 `cli.py`；已迁至 `_cli_parser.py`，门面只负责读取环境和传递当前 loader/normalizer。
- 修复后 CLI/HTTP/M41 回归 `397 passed`，最终边界聚焦 `483 passed`。CodeGraph 调用路径复核与 AST 检查均未发现反向依赖或循环。
- 归档后全量首次发现规划追溯测试仍固定指向 M40；已推进到 M41，并在通过专项后重新运行全量门禁。
- 当前会话策略禁止启动子代理，因此 standard review 由两轮独立自审完成；没有把该限制伪装成外部 reviewer 结论。

## 六项终值

- 性能：15 个独立进程，冷导入中位数 `110.761 ms`，parser 中位数 `0.547 ms`，低于 `136.140/0.672 ms` 阈值。
- 可靠性：聚焦 `483 passed`；全量 `2549 passed, 10 skipped in 166.20s`，M41 未新增 skip。
- 维护成本：`cli.py` 1789 行；四个边界分别为 306、230、615、780 行；8 个运行时直接依赖。
- 兼容性：帮助输出字节哈希、旧导入、动态 monkeypatch、HTTP shape、取消和资源关闭回归均通过。
- 团队能力：仅使用现有 Python、pytest、Ruff 与 uv，无新框架、注册器或代码生成。
- 迁移/回滚：无持久化迁移，提交按边界拆分；M41 前已有的 5 行 `receipt_store` 改动保持未提交。

## 验证证据

- `uv run pytest -q`：`2549 passed, 10 skipped in 166.20s`。
- 聚焦 pytest：`483 passed in 7.58s`。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：`134 files already formatted`。
- `uv build`：本地 sdist/wheel 构建成功，未上传。
- `git diff --check`：通过。
- `openspec validate --all --strict`：`32 passed, 0 failed`。

## 范围与边界

未执行包索引发布、tag、push 或发布自动化。未修改 Task、Loop、Collaboration、MCP、Memory、Skills 或 HTTP service 的领域契约；未覆盖工作区中进入 M41 前已有的用户改动。

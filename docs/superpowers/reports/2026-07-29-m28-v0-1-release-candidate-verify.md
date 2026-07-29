# M28 v0.1 Release Candidate 验证报告

## 结论

M28 仍在进行中。当前证据确认唯一 wheel 的 Python 3.11 clean install、CLI、HTTP、Single、Duo、
Triad 六项离线 smoke 通过，Linux required job 已配置，发布说明和五类已知限制已冻结；这些只构成
RC 工程冻结证据，不构成里程碑完成或正式发布结论。两项依赖宿主调度的 MCP 墙钟测试合同已用
确定性的预算转发断言修正，生产 MCP 代码未变，修正后完整 pytest 全绿。本机 Docker daemon 不可用，
且没有当前 M28 GitLab pipeline/job 证据。

## 范围

- 单一仓库级 RC harness、版本化 JSON 与失败关闭合同。
- packaging 真实 wheel 安装合同及 required Linux Docker CI 配置。
- `0.1.0` RC 说明、README、平台矩阵和已知限制冻结。
- 不包含 PyPI 上传、tag、push、真实 provider 请求或平台支持扩张。

## 新鲜验证

| 命令 | 结果 |
| --- | --- |
| `uv run pytest -q tests/test_m28_release_candidate_smoke.py tests/test_m28_release_ci.py tests/test_m28_release_docs.py tests/test_packaging.py` | `42 passed in 51.34s` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `119 files already formatted` |
| 首次 `uv run pytest -q` | `2 failed, 2401 passed, 10 skipped in 169.62s` |
| 修正后 `uv run pytest -q` | `2403 passed, 10 skipped in 167.99s` |
| `uv run python -m tests.golden.runner --output-dir artifacts/m28/golden` | exit 0；`report.md` 为 `20/20 passed (100.0%)` |
| `openspec validate --all --strict` | `22 passed, 0 failed` |
| `uv build --out-dir artifacts/m28/dist` | 唯一 wheel 与 sdist 构建成功 |
| `uv run python scripts/m28_release_candidate_smoke.py --wheel artifacts/m28/dist/forgeagent-0.1.0-py3-none-any.whl --output artifacts/m28/rc-smoke.json --python /Users/admin/.local/bin/python3.11` | exit 0；六项全通过 |

首次完整 pytest 的失败为：

- `test_capture_close_returns_before_duplicated_writer_reaches_eof`：`0.25006s < 0.2s` 断言失败。
- `test_close_wall_clock_is_bounded_by_shutdown_and_join_budgets`：`0.11171s <= 0.08s` 断言失败。

两个测试隔离复跑两次均为 `2 failed`；实测本机 `sleep(0.01)` 为 0.0238-0.0901 秒，说明当前
宿主调度不能满足这些绝对墙钟 slack。失败出现时，M28 从 merge-base 到 HEAD 对
`src/forgeagent/mcp_manager.py` 和 `tests/test_mcp_manager.py` 的 diff 为空；该历史失败没有被改写为 pass。

提交 `83ba892` 只修改 `tests/test_mcp_manager.py`，以确定性 probe 断言 stderr reader 的固定 join
请求，以及 shutdown future 和 loop-thread join 的转发预算；`src/forgeagent/mcp_manager.py` 保持不变。
修正验证为 focused `2 passed`、MCP suite `216 passed`、完整 pytest
`2403 passed, 10 skipped in 167.99s`，Ruff check/format 与 `git diff --check` 均通过。完整 pytest
门禁因此关闭，而不是把首次失败重新分类为环境 pass。

## RC JSON

- schema：`forgeagent.release-candidate-smoke/v1`
- version：`0.1.0`
- python：`3.11.15`
- wheel SHA-256：`d497df6a507adc7654c80b9042e4f96c838277bbabdeb031e1ca9c7f72bd4bdf`
- passed：`true`
- checks：`clean-wheel`、`cli`、`http`、`single`、`duo`、`triad` 均为 `passed`

报告不包含 provider secret、环境值、目标正文、模型回复或绝对临时路径。

## Docker 与 Linux 证据

Docker client 29.2.1 存在，但 `docker info` 返回：

```text
Cannot connect to the Docker daemon at unix:///Users/admin/.docker/run/docker.sock.
```

因此没有执行本机十项 `container_integration`，也没有生成 supplemental Linux-container
`linux-rc-smoke.json`。GitLab job 已配置为精确验证十项测试、唯一 wheel、六项 RC JSON 并始终发布
JUnit/JSON；在当前候选的 required job 实际通过前，它仍是 configured/pending。M24 Pipeline 50 /
Job 249 只作为历史 container-only 证据。

## Task Review 与修复

- Task 1 review 修复三类 Important：child report fail-closed、venv/pip/child 同一清洗环境，以及
  metadata/hash/install 绑定同一不可变 wheel snapshot；后续又收紧零退出报告的精确 schema、版本
  与 Python 版本合同。
- Task 2 review 修复 GitLab folded-shell 非 fail-closed 以及 bootstrap 安装失败不产出 JSON 的问题；
  现在 wheel 数量异常和 bootstrap 失败均退出非零并留下有界失败报告。
- Task 3 review 将证据测试从独立 token 升级为精确表格行绑定，拒绝 M28 Linux 成功夸大，并把
  resume 限制精确到协作专用 endpoint。
- Task 4 review 发现里程碑生命周期过早收口和完整 pytest 阻塞表述不一致；`e696737` 恢复进行中
  状态，`83ba892` 以 tests-only 可移植性合同关闭完整 pytest 门禁，生产 MCP 实现不变。
- Task 1-3 task-level review 的发现均已修复；最终整分支 review 与两轮一致性复审仍属于后续 verify
  gate，本报告不提前宣称完成。

关键提交 provenance：Task 1 为 `9586c70`、`31eff32`、`426e234`、`2eaab53`；Task 2 为
`6bc760a`、`00ad211`、`44125e5`；Task 3 为 `03e1983`、`887608e`、`2b476d3`；Task 4 验证与
证据草案为 `37365bd`，lifecycle 修正为 `e696737`，MCP 测试合同修正为 `83ba892`。这些提交证明
实施和 review fix 的来源，不替代仍开放的 lifecycle gate。

## OpenSpec 场景映射

### release-candidate-verification

| Requirement / Scenario | 证据 |
| --- | --- |
| 干净 wheel 安装成功 / 源码树遮蔽安装缺陷 | focused packaging + RC suite 42 passed；唯一 wheel harness 的 `clean-wheel=passed`；snapshot/import provenance 负向合同 |
| CLI 离线确定 / entry point 或资源缺失 | `cli=passed`；console script 与包内模型信息由安装环境运行；缺失入口/资源使 harness 非零 |
| HTTP 生命周期 / 鉴权 | `http=passed`；真实 loopback submit/query/cancel、401 不创建任务和有界关闭合同 |
| Single/Duo/Triad 完成 / 角色回归 | 三项均 `passed`；真实 runtime + MockClient 固定 structured submit，任一角色失败使后续非通过 |
| JSON 全通过 / 检查失败 | schema v1 六项全通过；Task 1 fail-closed、精确字段、原子 replace 与脱敏负向合同 |
| RC 发布说明 / 限制弱化 | 文档专项包含在 42 passed；五类限制、configured/historical 边界和反夸大 mutation 合同 |

### continuous-verification

| Scenario | 证据 |
| --- | --- |
| Docker ready | CI 配置保持 daemon/image preflight 与精确十项零 skip；本机未满足，未执行 |
| daemon/image unavailable | 当前 `docker info` 非零；按合同不进入 pytest，不产生成功结论 |
| container skip/fail | CI/JUnit 合同测试包含在 focused 42 passed；没有本轮执行结果 |
| installed-wheel RC smoke passes on Linux | job 配置、唯一 wheel 与六项 JSON 合同存在；无当前 pipeline，状态 configured/pending |
| installed-wheel incomplete/fails | wheel cardinality、bootstrap fallback、JSON exactness 均 fail closed；Task 2 review fix 验证 |

## 已知限制与正式发布阻塞

- 平台：当前 M28 required Linux job 未执行；不外推 Podman、Windows 或其他 Linux topology。
- 真实模型：harness 只用 MockClient，未读取凭据、外发请求或产生费用。
- sandbox：restricted 是应用层边界；container 依赖 daemon/镜像/宿主，不是多租户密封边界。
- HTTP：仅 loopback + bearer，无 TLS、公网反代或多租户承诺。
- 协作 v1：没有协作专用 resume endpoint；headless Triad 默认不自动批准计划。
- 完整 pytest：首次两个 MCP 墙钟测试失败已由 `83ba892` 的 tests-only 可移植性修正关闭；新鲜全量为 `2403 passed, 10 skipped`，生产 MCP 代码未变。

本报告是进行中证据快照，不关闭 M28。正式发布仍要求当前 M28 Linux required job 通过并保留
pipeline/job artifact、最终 review/两轮复审及 archive 完成，以及另行授权的 tag/上传动作。

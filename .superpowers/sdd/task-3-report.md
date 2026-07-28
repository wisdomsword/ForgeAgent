# M27 Task 3 Report: 文档合同与公开状态

## 状态

`DONE`

## RED

先修改 `tests/test_collaboration_docs.py` 与
`tests/test_continuous_verification.py`，再运行：

```text
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  tests/test_collaboration_docs.py tests/test_continuous_verification.py

5 failed, 9 passed
```

失败分别证明 README 仍要求编程任务强制 Triad、仍将 Memory 写为只读，HTTP 文档仍描述
`needs_confirmation` 和 weaker override，Threat Model 未限制宿主检查事实，以及平台矩阵仍把
未记录的 `amd64/arm64` 共同标为 verified 并遗留 Linux configured 结论。

## GREEN

```text
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  tests/test_collaboration_docs.py tests/test_continuous_verification.py

14 passed in 0.10s
```

文档合同现在要求 README 与 HTTP 文档表达默认 Single、显式模式优先、可信宿主的非空冻结检查才
自动 Triad，且 `allow_weaker_override` 只保留配置兼容、没有路由或确认作用。README 还改正了
M18 Memory：runtime 准入后的原子持久化、用户直接编辑、`--no-memory` 与 `--no-identity` 的边界。

平台矩阵将 Pipeline 50 / Job 249 收窄为已执行的 Linux Docker runner topology，删除未记录
架构的暗示与过期 configured 结论。README 和 platform-support 的当前基线保持相同的 M26
已记录数字；M27 最终全量结果由 Task 4 统一更新。

ACTION_PLAN 增加未归档的 M27 条目，链接 M25 派生报告，并记录没有类别恢复自动 Triad。

## 自审

- 路由文字没有把候选文件要求或任务文本重新当作自动 Triad 证据。
- Memory 更新仅修正公开合同，没有触碰 M18 运行时或身份禁用语义。
- Linux 仍为 verified，但仅针对 Pipeline 50 / Job 249 已记录 runner topology；不推断架构。
- M25 派生报告只被引用，未修改冻结输入或派生产物。

## 风险信号

- 当前 pytest/OpenSpec/Golden 数字仍是 M26 已记录基线；Task 4 必须在最终全量验证后同步更新。
- `has_bound_checks` 是可信宿主的内部事实；公开客户端不得提交或伪造该事实。

## Reviewer 修复轮

### RED

先补三项公开边界合同，再运行：

```text
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  tests/test_collaboration_docs.py tests/test_continuous_verification.py

3 failed, 13 passed
```

三个失败分别证明：README 未明确显式模式优先于宿主冻结检查，未把
`has_bound_checks` 限为不能由 HTTP/普通任务请求/服务器 YAML/任务文本伪造的可信宿主内部事实，
也未明确 session scope 仅在当前 REPL 进程内且绝不落盘；首页还把 Linux verified 写得比
`Linux Docker runner topology (Pipeline 50 / Job 249)` 更宽。

### GREEN

README 现明确 session scope 仅当前 REPL、绝不落盘；只有确定性准入后的合法 project scope 候选
才会在稳定本地锁内重读合并并原子持久化。路由段明确显式模式优先，并锁定
`has_bound_checks` 的可信宿主内部来源与公开输入禁止项。首页仅声明已记录的 Linux Docker runner
topology，不推断架构。

```text
UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q \
  tests/test_collaboration_docs.py tests/test_continuous_verification.py

16 passed in 0.09s
```

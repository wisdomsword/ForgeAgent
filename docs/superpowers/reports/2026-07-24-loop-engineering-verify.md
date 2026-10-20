# M21 Loop Engineering 验证报告

- Change: `loop-engineering`
- 实现验证提交: `24ce554a6b39f0f06a7ed4ec95ecfc314d284998`
- 归档提交: `bd819af`
- 验证模式: full
- 结论: PASS，已合并 `main` 并归档

## 结果总览

| 维度 | 结果 |
| --- | --- |
| 完整性 | 13/13 OpenSpec tasks；10/10 requirements 已实现 |
| 正确性 | 39/39 scenarios 有实现与确定性测试或静态契约证据 |
| 一致性 | proposal、delta specs、OpenSpec design、技术 Design Doc 与实现一致 |
| 代码审查 | thorough 逐任务审查 + 全变更终审；最终无 Critical/Important |

## 实现与场景证据

- `src/forgeagent/loop.py`：严格 `forgeagent.loop.v1` 模型、固定 stop reason、目录 fd 固定、相对原子替换、revision 检查、Checkpoint 工具、LoopRunner、预算/取消/失败收敛与最小审计。
- `src/forgeagent/cli.py`：`forgeagent loop` 新建/resume、严格参数、SIGINT 协作取消、安全报告、逐迭代 Task/client 关闭；普通 `run`/REPL 保持单 Task 且不自动调用 Evaluator。
- `src/forgeagent/http_server.py`、`src/forgeagent/http_task_service.py`：既有 `/tasks` 的三种严格 schema、server-owned 执行策略、Loop 公共投影、same-ID overlap 防护、取消线性化、TTL/capacity/资源关闭兼容。
- `tests/test_loop_checkpoint.py`：损坏、未知 schema、大小/字段边界、symlink 与父目录替换竞态、原子失败保留旧字节、stale revision、Checkpoint commit-before-success。
- `tests/test_loop_runner.py`：create/resume、不重做完成项、所有停止条件、usage unavailable、失败修正、取消/完成与墙钟竞态、审计字段、MCP/Skills registry、资源关闭。
- `tests/test_cli.py`、`tests/test_http_task_service.py`、`tests/test_http_server.py`：CLI/HTTP 输入、输出、退出码、取消、隔离、公开最小披露、普通路径兼容与 Evaluator 热路径边界。
- `tests/test_loop_docs.py` 与 `examples/loop/`：cron、launchd、systemd service/timer、HTTP 调用和只报告依赖状态的无副作用示例。

## 新鲜验证证据

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run pytest -q
1758 passed, 11 skipped in 84.87s

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff format --check .
91 files already formatted

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run ruff check .
All checks passed!

git diff --check a72076c8475ea1712fdea2e0a60669cabd03b9dd..HEAD
exit 0

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv run python -m tests.golden.runner \
  --output-dir /tmp/forgeagent-m21-golden-final
Summary: 20/20 passed (100.0%)

UV_CACHE_DIR=/tmp/forgeagent-m21-uv-cache uv build \
  --out-dir /tmp/forgeagent-m21-dist-final
Successfully built forgeagent-0.1.0.tar.gz and forgeagent-0.1.0-py3-none-any.whl

openspec validate --all --strict
Totals: 16 passed, 0 failed (16 items)
```

归档提交后再次执行完成门禁：

```text
UV_CACHE_DIR=/tmp/forgeagent-m21-final-uv-cache uv run pytest -q
1758 passed, 11 skipped in 76.43s

UV_CACHE_DIR=/tmp/forgeagent-m21-final-uv-cache uv run pytest -q \
  tests/test_loop_checkpoint.py tests/test_loop_runner.py tests/test_cli.py \
  tests/test_http_task_service.py tests/test_http_server.py
462 passed in 5.84s

UV_CACHE_DIR=/tmp/forgeagent-m21-final-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m21-final-uv-cache uv run ruff format --check .
91 files already formatted

UV_CACHE_DIR=/tmp/forgeagent-m21-final-uv-cache uv run python -m tests.golden.runner \
  --output-dir /tmp/forgeagent-m21-golden-post-archive
Summary: 20/20 passed (100.0%)

UV_CACHE_DIR=/tmp/forgeagent-m21-final-uv-cache uv build \
  --out-dir /tmp/forgeagent-m21-dist-post-archive
Successfully built forgeagent-0.1.0.tar.gz and forgeagent-0.1.0-py3-none-any.whl

openspec validate --all --strict
Totals: 16 passed, 0 failed (16 items)
```

首次归档后全量测试暴露 1 个收尾契约遗漏：`tests/test_loop_docs.py` 仍要求 ACTION_PLAN
把 M21 标为“进行中”。该测试已改为校验“已完成并归档”及最终实证计数，专项 6/6 与随后
完整套件均通过；这不是 Loop 运行时回归。

Sandbox 内首次全量测试为 `1726 passed, 23 skipped, 12 failed`；11 项失败来自 loopback 端口权限，1 项来自嵌套 `uv build` 权限。使用相同命令提升权限后得到上方最终通过结果，未弱化测试。

## 审查与修复

- Checkpoint 审查修复 token overshoot、Unicode 控制字符、稳定报告 schema/stop reason、文件与父目录 symlink TOCTOU、fd 复用和目录换绑竞态。
- Runner 审查修复零 usage、失败摘要长度/诊断计数、严格完成优先级、MCP/Skills registry 装配。
- CLI/HTTP 审查修复 SIGINT 持久化取消、systemd timer 示例、取消/完成竞态、审计字段完整性和逐迭代 client 关闭。
- 全变更终审在 `7d27f49` 与 `24ce554` 后复审通过：无 Critical/Important findings。

## 两轮最终自审

1. 需求/产物一致性：逐项核对 13 tasks、10 requirements、39 scenarios、proposal、OpenSpec design、技术 Design Doc 和 ACTION_PLAN；未发现遗漏或矛盾。
2. 数据流/边界：复核 revision、原子写、目录 fd、重复副作用边界、预算优先级、timer/cancel 竞态、Task/client/store close、HTTP 线性化、secret/path/text 最小披露、M20/M22 隔离；未发现剩余阻塞问题。

## 接受的限制

- Checkpoint 是提交边界；最后一次成功 Checkpoint 之后、Task 返回之前的未提交外部副作用可能在恢复时重做，不承诺 exactly-once。
- 同一 checkpoint 的跨进程并发没有全局锁；CLI 文档要求调度器避免重叠，HTTP 服务在单进程内拒绝 same-ID overlap。
- 墙钟和 Ctrl+C 为协作取消，不能强杀已在途 provider/tool 调用，只在下一个安全边界持久化终态。
- M20 Evaluator 保持 opt-in；M21 不实现 M22 Planner/Generator/Evaluator 打回语义。

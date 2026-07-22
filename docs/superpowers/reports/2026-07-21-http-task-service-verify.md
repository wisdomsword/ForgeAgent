# M16 HTTP Task Service 验证报告

- 日期：2026-07-22
- Change：`http-task-service`
- 验证模式：full
- 基准：`e02c5104ef30e19433fc88562e9d7cc78a330130`
- 最终实现：`f4a3ef7`（后续提交仅更新验证证据与 Comet 状态）

## 结论

| 维度 | 结果 |
| --- | --- |
| 完整性 | PASS：22/22 tasks，10/10 requirements |
| 正确性 | PASS：39/39 scenarios 有实现和测试映射 |
| 一致性 | PASS：proposal、OpenSpec design、技术 Design Doc 与实现无矛盾 |
| 代码审查 | PASS：whole-change 最终复审无 Critical/Important |

最终结论：没有 CRITICAL 或 WARNING。实现满足归档条件。下文记录的残余风险和
环境限制均已在用户文档、威胁模型和测试证据中明确，不属于放宽运行时安全策略。

## OpenSpec 映射

- `http-task-service`：严格 bearer 鉴权、请求 schema、三条路由、安全结果投影、
  取消终态、并发隔离、容量/TTL、结构化错误和 owner shutdown 分别由
  `http_config.py`、`http_server.py`、`http_task_service.py`、`task.py`、
  `step.py` 与对应 HTTP/TaskService/CLI 测试覆盖。
- `audit-logging`：核心 tool/LLM/confirmation/HTTP lifecycle 事件、task/operation/
  attempt correlation、掩码、JSONL fallback、并发 append、按字节轮转、`0600`、
  startup fail-closed 和 runtime fail-open/degraded 由 `audit.py`、`secret_policy.py`
  及 audit/task/step/tools/http 测试覆盖。
- `tool-approval`：精确 typed allowlist 覆盖 MCP、FileWrite、WebFetch 初始 URL 和
  每个 redirect hop。最终修复 `f4a3ef7` 将 `allow_auto_approve=False` 从 HTTP
  `serve` factory 显式传递到 `Task -> Step -> ToolContext`；端到端回归证明空 HTTP
  allowlist 下既不查询 MCP `autoApprove`，也不执行 MCP 调用。CLI/REPL 默认仍为
  `True`，保留既有兼容语义。

## 验收覆盖

- 基于 `socket.socketpair()` 驱动真实 `ForgeRequestHandler` 请求循环，覆盖完整
  request line、Bearer header、JSON framing、dispatch 和 response parsing。8 路并发
  提交获得不同 task id；worker gate 释放前均为非终态，释放后在 5 秒 deadline 内
  轮询到独立终态。
- G13 使用等价 MockClient script 比较 direct Task 与完整 HTTP `POST` + 轮询 `GET`
  路径；两者均为 `completed`、3 rounds、2 tool outcomes，HTTP 投影不包含模型文本、
  工具 stdout 或原始错误。
- TaskService shutdown 验证 worker/cleanup 线程退出和共享 MCP manager 单次关闭；
  其余测试覆盖取消竞态、容量、TTL、鉴权、脱敏、审计 degraded 和资源失败路径。

## 命令与证据

| 命令 | 结果 |
| --- | --- |
| `PYTHONPATH=src .venv/bin/pytest -q --ignore=tests/test_packaging.py` | PASS：1221 passed，23 skipped，50.99s |
| HTTP autoApprove 回归 + tools + headless focused | PASS：63 passed |
| HTTP/mock/headless focused | PASS：98 passed，10 skipped |
| 并发/shutdown/G13 focused 连续 5 次 | PASS：每次 3 passed，5/5 |
| `.venv/bin/python -m tests.golden.runner` | PASS：exit 0；artifact 报告 20/20（100%） |
| `.venv/bin/ruff check src tests` | PASS：`All checks passed!` |
| changed-file `ruff format --check` | PASS |
| `openspec validate http-task-service --strict` | PASS |
| `git diff --check` | PASS，无输出 |
| `PYTHONPATH=src .venv/bin/pytest -q tests/test_packaging.py` | 环境失败：2 passed，1 failed；内部 `uv build` exit 2 |
| `UV_CACHE_DIR=/tmp/forgeagent-m16-final-uv-cache uv build --out-dir /tmp/forgeagent-m16-final-build` | 环境失败：3 次重试后无法通过 DNS 获取 PyPI `hatchling` |

Comet 的 build guard 自动探测器只识别 npm/Maven/Cargo，Python 项目会在无匹配时
直接返回失败。实际项目验证已显式执行并记录，因此 build guard 使用命令级
`COMET_SKIP_BUILD=1` 只跳过不适用的自动探测；没有跳过上述 pytest、Ruff、golden、
OpenSpec 或 diff 验证。

仓库级 `ruff format --check` 还会报告 6 个本 change 之前已存在的未格式化文件
（`executor.py`、`model_discovery.py`、`protocol.py` 和 3 个既有测试）；M16 修改的
Python 文件均通过格式检查，未扩大范围重写无关文件。

10 个 focused skip 是真实 loopback listener 测试。当前 managed sandbox 对
`bind(('127.0.0.1', 0))` 返回 `PermissionError: [Errno 1] Operation not permitted`；
测试只对该明确权限错误 skip。完整 handler/framing/auth/dispatch/concurrency 路径由
无 bind 的 socketpair 测试通过。packaging 失败同样是 DNS 环境限制，不是产品 fallback。

## 已接受残余

- FileWrite canonical path 校验与 pathname open 之间仍有 hostile-host symlink TOCTOU。
- 协作取消不能打断正在进行的 provider/tool 调用，只在安全边界生效。
- audit 启动压缩可能一次性读取整个旧日志文件。
- Unix 路径行为已覆盖，没有专门的 Windows UNC 验收。
- 客户端在错误 envelope 写出期间断连时，`socketserver` 可能输出诊断 traceback，
  但不会重复 lifecycle audit，也不会进入 JSON 响应。
- 实际 listener bind 和 wheel/sdist 构建需要在允许 loopback 与 PyPI DNS 的环境补跑；
  这些限制不会放宽 loopback-only、token、allowlist 或 audit 策略。

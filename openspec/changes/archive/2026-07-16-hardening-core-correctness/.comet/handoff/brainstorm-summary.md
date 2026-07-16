# Brainstorm Summary

- Change: hardening-core-correctness
- Date: 2026-07-13

## 确认的技术方案

- 采用“原边界内最小加固”：不新增统一策略层或 hardening 子系统，产品改动限定在现有 SSRF、CLI confirmer、Step 完成状态和 MCPManager 边界。
- `guarded_urlopen()` 显式使用 `ProxyHandler({})` 禁用环境代理，继续复用已有 guarded HTTP/HTTPS connection、地址分类和 NAT64 判断；新增 guard-owned redirect handler，最多允许 10 跳且只允许 HTTP/HTTPS。
- confirmer 保持 `Callable[[BaseModel], bool]`。MCP arguments 递归按现有 secret-name policy 脱敏，URL 脱敏 userinfo/敏感 query/已知 secret value，FileWrite 只显示项目相对路径或外部 basename 与内容长度。REPL 始终注入，单次 run 仅在 stdin/stdout 都是 TTY 时注入，且不再依赖 MCP 是否存在。
- MCP 既有 `autoApprove` 保持为显式预批准；非 TTY 默认拒绝只适用于仍需人工确认的调用。WebFetch/FileWrite 没有预批准例外。
- Step 根据 `parsed.tool_calls` 和 `parsed.errors` 计算完成资格；存在任一项时忽略同轮 `completed: true` 并反馈下一轮。refused/need_info/failed 等现有显式终止语义不扩大修改。
- `MCPServerConfig` 增加 `required: bool = False`。enabled optional 服务失败时诊断并继续；enabled required 服务失败时，CLI 先 best-effort close，再报告包含服务名和状态的 `MCPStartupError` 并退出 2。required 只约束初始启动，不限制 REPL 运行期显式 enable/disable。
- `MCPManager.close()` 先置 `_closed`，再以 `time.monotonic()` 绝对 deadline 管理正常 holder、cancel、loop stop 和 thread join；总上限仍为默认 10 秒 shutdown + 2 秒 join，阶段只消费实时剩余额度并为 join 保留预算。整个公开边界防御性捕获 Exception，关闭错误只 warning，不覆盖任务结果或启动错误。
- 未来代理契约只在文档中预留 `network.proxy.url` 与 `network.proxy.no_proxy`；本里程碑运行时不读取该配置，也不实现代理转发。
- 黄金核心采用类型化 Python manifest，限定在 `tests/golden/`。确认的通用任务为 G01/G03/G05/G08/G11/G13/G15/G17/G27/G43；加固边界为 G06/G14/G58/G59/G324/G329/G330/G332/G333/G355。
- 真实模型 opt-in 子集为 G01/G03/G08/G11/G43；命令显式指定单个模型，缺配置或凭证时在执行场景前退出 2，不生成通过率报告。
- runner 输出 `artifacts/golden/offline/` 或 `artifacts/golden/real/<model-id>/` 下的 `results.json` 与 `report.md`；全通过退出 0，任一场景失败时写完整报告并退出 1，manifest/模型/输出目录等 preflight 失败退出 2。

## 关键取舍与风险

- 禁用环境代理会改变依赖系统代理的隐式联网行为；这是 `[SECURITY][BREAKING]` 安全收紧，文档必须明确当前仅支持 guarded direct connection。
- 严格两阶段完成会让工具任务至少增加一次模型往返；这是让模型看到工具结果后再确认完成的必要成本。
- optional MCP 降级可能被忽略；CLI 必须打印服务名和失败状态，生产必需服务应配置 `required: true`。
- MCP SDK 正常进程清理最坏约 4 秒；默认 12 秒绝对 deadline 是外层最终边界。若后台线程仍未退出，只能 warning 并依赖 daemon 线程不阻塞 CLI，因此专项测试必须验证正常和无响应 fixture 不遗留子进程。
- 20 项核心不能代表全部 380 项；文档必须明确其余 360 项只是候选，不能宣称已验证。
- Python manifest 比 YAML 更不便于非开发者编辑，但避免字符串注册表、重复校验层和新评测框架，符合当前最小范围。

## 测试策略

- 先固化环境代理绕过、三类 confirmer、TTY/非 TTY 注入、工具/parse 完成门控、MCP required 和 close 超时/幂等的失败回归。
- `tests/conftest.py` 用 `pytest_sessionstart` 为每个 pytest/xdist worker 创建唯一临时 HOME/USERPROFILE，在测试模块收集前隔离 import-time `Path.home()` 常量；`pytest_sessionfinish` 清理。函数 fixture 无法覆盖已计算常量，因此不作为全局隔离手段。
- SSRF loopback 拒绝测试不启动本地 server；环境代理测试通过假公有代理地址和 socket 插桩证明校验目标不再是代理。新增 10 跳上限、非 HTTP 重定向测试；必须绑定本地端口的集成测试先探测能力，不可用时有理由地 skip。
- MCP fixture server 写唯一 PID 文件，泄漏测试按 PID 检查存活和退出，替换全局进程计数断言。
- `tests/golden/manifest.py` 在 runner preflight 验证 20 个唯一 ID、精确集合和 5 个 real callable；`cases.py` 负责每场景独立临时目录、执行和显式判定；`runner.py` 收敛异常并由同一结果对象生成 JSON/Markdown。
- 现有 G01/G05/G13 回放迁移为黄金 cases 的共享实现，pytest 只验证 manifest/runner/report 合约和代表场景，避免重复场景代码。
- pytest 额外检查 20 个 manifest ID 在 `docs/golden-tasks-seed.md` 中仍有任务定义；不在 Markdown 中维护第二套 `[CORE]` 标签事实源。
- 完成前运行 Ruff、隔离 HOME 全量 pytest、SSRF/CLI/Step/MCP 专项测试、20 项离线黄金 runner 和 CodeGraph 调用路径复审；Docker、公网和真实模型按环境能力与 opt-in 状态诚实报告。

## Spec Patch

- `tool-approval`: 明确非 TTY 默认拒绝只适用于仍需人工确认的调用；MCP `autoApprove` 是显式配置预批准，继续跳过人工确认。
- `golden-validation-core`: 固定 20 个离线核心 ID 和 5 个真实模型 ID；增加显式真实模型缺配置/凭证时退出 2 且不生成通过率报告的场景。
- `mcp-resilience`: 明确 `required` 只作用于 enabled 服务的初始 CLI 启动，运行期用户显式 enable/disable 不终止已运行 REPL。
- `network-boundary-safety`: 增加 guard-owned 10 跳上限和 HTTP/HTTPS 重定向 scheme 限制。
- `tool-approval`: 增加结构化敏感键、URL 和绝对路径的最小披露契约，并要求非 TTY 拒绝说明缺少交互通道。

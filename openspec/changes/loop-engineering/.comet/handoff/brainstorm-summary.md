# Brainstorm Summary

- Change: loop-engineering
- Date: 2026-07-24

## 确认的技术方案

在现有 `Task` 上方新增轻量 `LoopRunner`，每次迭代创建一个全新的 Task；Loop 只持久化跨迭代进度、失败证据与累计预算，不序列化 conversation、Runtime、代码块或 executor。通过只在 Loop registry 中注册的 `Checkpoint` 工具，让模型在 Task 中途原子提交 completed items、open questions 和 handoff；Task 返回后 runner 自动提交 counters 与终态。

checkpoint 使用 `<allowed_root>/.forgeagent/loops/<loop_id>.json` 的严格版本化 JSON，拒绝 symlink/路径逃逸/未知字段/超限内容，以 sibling temp + flush/fsync + `os.replace` 原子写入。新 Loop 必须显式提供 token budget；默认累计 rounds=50、wall clock=3600 秒、consecutive failures=3。恢复冻结 goal/budgets，终态 Loop 不再次执行。

CLI 新增 `loop` 子命令；HTTP 复用现有 `POST /tasks`、线程池、取消、TTL 和审计，通过严格可选字段选择普通 Task、新 Loop 或 resume。普通 `run`/REPL/HTTP 请求不变。cron/launchd/systemd 只提供调用示例，不内置 scheduler。

## 关键取舍与风险

- 选择 Task 上层控制器，拒绝侵入 Step resume 与通用 workflow engine，缩小 blast radius。
- checkpoint 是 durable commit boundary，不承诺未提交副作用 exactly-once；恢复只跳过已提交条目。
- 墙钟超时沿用 cooperative cancellation，不能强杀在途 provider/tool call；在首个安全边界终结。
- token budget 配置后，成功调用若 usage 全零则以 `token_usage_unavailable` 停止，避免未知用量绕过预算。
- checkpoint 文本按不可信数据、有界、脱敏注入；不携带权限配置，不自动调用 M20 Evaluator，不实现 M22 打回环。

## 测试策略

使用 TDD。核心模型/store/tool/runner 以 MockClient 和 fake clock/watchdog 做确定性测试；覆盖 checkpoint 中途提交后模拟 kill/resume、不重做完成项、原子失败、symlink/path/size/schema 拒绝、每种 stop condition、条件竞争优先级、失败修正收敛、audit 最小披露。CLI/HTTP 覆盖严格参数 schema、普通路径兼容、cancel/TTL/并发隔离。最终运行专项、全量 pytest、20/20 trusted golden、Ruff、build、OpenSpec strict 和 diff check。

## Spec Patch

已修正 HTTP spec 拼写，并固定默认预算：token budget 必须显式提供；累计 rounds=50、wall clock=3600 秒、consecutive failures=3。

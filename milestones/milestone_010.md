# 里程碑 M10: 用量可观测性 + WebFetch/File 工具生态扩展

- 状态: 已完成
- 起止: 2026-07-11 ~ 2026-07-12
- 对应 ACTION_PLAN 行: M10（见该文件 §四 里程碑表；M9 顺延跳过，见 ACTION_PLAN 首段用户裁决）
- 前置里程碑: [milestone_008](milestone_008.md)

## 目标与范围

摘自 ACTION_PLAN.md §四 M10 行：

- 交付物：用量/计费可观测性（CLI 状态栏，显示 token 使用量 input/output/cached 等）；golden 任务集适量扩展；工具生态扩展（WebFetch + FileRead/FileWrite/FileList，SSRF 逐跳复检 + project-root 锁定，零新依赖），`restricted` 档下 WebFetch 和 FileWrite 必须触发确认门，FileRead 可记录日志。
- 验证：—（未预设具体命令，由本里程碑自定义验收证据）。
- 门禁：视需求排期（弱门禁，不要求用户显式批准）。

设计依据：`docs/m10-usage-observability-and-tools.md`（12 项裁决全部裁决完成 + §八 Phase-0 spike 实测记录 + §四 threat-model 增量 T10a-T10c）。

## 方案设计

12 项裁决（`docs/m10-usage-observability-and-tools.md` §五，全部裁决完成）核心内容：

1. **两个正交增量**：用量可观测性（`TokenUsage.cached_tokens` + CLI 状态栏）与工具生态扩展（WebFetch + File 工具）彼此独立，无共同前置依赖，可并行开发。
2. **SSRF Guard 落点**：`urllib.request` 的 `_create_connection` hook 拦截每个候选地址,`getaddrinfo` 解析出的每个 sockaddr 逐一过 `is_global`/`is_multicast`/NAT64（`64:ff9b::/96`）解包复检；直连已过校验的 sockaddr（不重新解析域名，堵 DNS rebinding 的 TOCTOU 窗口）；`HTTPRedirectHandler` 天然逐跳重触发 `http_open`/`https_open`，同一 hook 免费获得逐跳复检。**已知易错点**（Phase-0 spike 发现）：`_create_connection` 必须在 `__init__` 内以实例属性覆盖，类属性覆盖会被 `http.client.HTTPConnection.__init__` 静默遮蔽。
3. **WebFetch 混合返回设计**：完整（可能截断）body 落盘到 `allowed_root` 下，`detail` 只带小体量 preview——避免不可信网页内容直接大段进入模型上下文。`MAX_FETCH_BYTES=1MB`，`PREVIEW_CHARS=2048`。GET-only，无 method/headers 字段（通用 HTTP 客户端语义留给 MCP，非 WebFetch 职责）。
4. **File 工具 project-root 锁定**：`_validate_path` 做 realpath 前缀校验，在主进程内独立实现（不经 executor 后端，因为 File 工具跑在主进程）。FileList 只返回相对路径，不泄露宿主目录结构。FileRead 内容经 `mask_secrets()` 掩码；FileWrite 内容不掩码（掩码会破坏用户预期的文件内容）。
5. **确认门的安全边界差异（M10 安全模型的关键）**：WebFetch 的确认门是**真实安全边界**——`restricted`/`container` 档下 Exec 已被 audithook 全拒出网（T3），WebFetch 是当前唯一出网路径，拒绝确认即拒绝全部出网。FileWrite 的确认门是**UX 层提示,非安全边界**——模型代码经 Exec 本就能在 `allowed_root` 内任意写（executor 后端的 audit hook 早已放行项目目录内写操作），拒绝 FileWrite 确认门不能阻止等价的 Exec 写入。两者的代码注释与 threat-model 文档均需如实标注这一差异，不可混淆或过度承诺。
6. **零新依赖**：全部新代码（SSRF Guard、WebFetchTool、File 工具）仅用标准库（`http.client`/`ipaddress`/`socket`/`urllib.request`/`os`/`pathlib`/`hashlib`），复用既有 `secret_policy.mask_secrets`/`sensitive_env_values`。
7. **`ToolContext` 扩展**：`tier`/`allowed_root` 字段，且解析值须与 executor 后端的 `allowed_root` 完全一致（同一次 `str(Path(...).resolve())` 计算结果传给两处），否则 File 工具的锁定范围与 Exec 的沙箱范围会漂移。`Tier`/`Confirmer` 类型移至 `tools.py`（消解与 `task.py` 的循环 import），`Confirmer` 泛化为 `Callable[[BaseModel], bool]`。
8. **多模态用量字段**：spike-then-decide,若无稳定形状不预留占位字段——本里程碑未触发该需求,未新增。

Phase-0 spike（`docs/m10-usage-observability-and-tools.md` §八）关键发现：`_create_connection` 类属性覆盖会被实例属性静默遮蔽（已在设计中修正为 `__init__` 内实例属性覆盖）；`HTTPRedirectHandler` 逐跳重触发验证（两个本地 `HTTPServer` 构造的跳转链路验证）；IP 校验矩阵需额外覆盖多播（`is_global=True` 但需另判 `is_multicast`）与 NAT64（`64:ff9b::/96` 不会被 `ipaddress` 自动解包,需手动检测并递归复检嵌入的 IPv4）。

对抗性代码评审（本里程碑收尾时执行，非委派 subagent——环境暂无可用 `code-reviewer` 类型且并行开发过程已产生足够交叉验证，改为直接阅读全部落地代码 + 针对性 PoC 验证假设）：重点复核 SSRF Guard 是否存在重定向到 `file://` 绕过 scheme 检查的漏洞——构造本地 HTTP 服务器返回 302 跳转到 `file://` 路径的 PoC，实测 Python `urllib.request.HTTPRedirectHandler` 自身即拒绝非 http(s) 的跳转目标（`HTTPError: Redirection ... is not allowed`），与 WebFetch 自身的 scheme 前置校验构成双重防护，无绕过路径。File 工具的 `_validate_path`、WebFetch 的确认门/掩码/落盘路径、两个 LLM client 的 `cached_tokens` 映射（含 `usage`/`prompt_tokens_details` 缺失时的防御性 `getattr` 链）、CLI 用量累加器（`RoundResult.usage is None` 时跳过、REPL 跨任务持续累加）均逐一读取最终落地代码确认，未发现真实缺陷。

## 子任务清单

- [x] Phase 0：设计文档 `docs/m10-usage-observability-and-tools.md` 撰写 + 用户评审（12 项裁决全部确认）+ Phase-0 spike 完成（SSRF Guard 关键 bug 在设计阶段即发现并修正）
- [x] Phase 1：`TokenUsage.cached_tokens` 字段 + 两个 LLM client 的 usage 映射（Anthropic 求和 cache_creation/cache_read；OpenAI-compatible 兼容 `prompt_tokens_details` 缺失）
- [x] Phase 2：`src/forgeagent/ssrf_guard.py`（SSRF Guard 模块）+ `tests/test_ssrf_guard.py`（IP 矩阵/NAT64/逐跳复检/scheme 拒绝/`_create_connection` 遮蔽回归测试）
- [x] Phase 3：`WebFetchTool` + `WebFetchArgs`（GET-only + 混合落盘/preview 返回 + 确认门）
- [x] Phase 4：`FileReadTool`/`FileWriteTool`/`FileListTool` + `_validate_path` + 对应 Args 模型
- [x] Phase 5：CLI 会话级 token 用量状态行（`run_once`/`repl` 累加器 + `rich.console` 打印）
- [x] Phase 6：`docs/golden-tasks-seed.md` 扩展 G321-G340（20 个，8/5/4/2/1 精确维持 40/25/20/10/5% 配比），总数扩到 340
- [x] Phase 7：`docs/threat-model.md` 新增 T10a-T10c 行 + 本里程碑文件收尾 + `milestones/latest` 更新

本里程碑的 Phase 1/2/3+4/5/6 由 5 个并行 subagent 同时开发（用户裁决"可以分为至少 5 个 agent 同时开发"）；Phase 3 与 Phase 4 因共同触及 `tools.py`/`protocol.py`/`default_registry()` 合并为一个 agent 承接，避免文件级冲突；Phase 7 待前 6 项全部落地后统一执行。

## 交付物清单

- [x] `src/forgeagent/models.py` — `TokenUsage.cached_tokens: int = 0`
- [x] `src/forgeagent/anthropic_client.py` — `_parse_response` 新增 `cached_tokens` 映射（cache_creation + cache_read 求和）
- [x] `src/forgeagent/openai_compatible_client.py` — `_parse_response` 新增 `cached_tokens` 映射（`prompt_tokens_details.cached_tokens`，容错缺失）
- [x] `src/forgeagent/ssrf_guard.py` — 新增，`SSRFGuardError`/`_is_blocked`/`_guarded_create_connection`/`_GuardedHTTPConnection`/`_GuardedHTTPSConnection`/`_GuardedHTTPHandler`/`_GuardedHTTPSHandler`/`guarded_urlopen`
- [x] `src/forgeagent/tools.py` — 新增 `WebFetchTool`/`FileReadTool`/`FileWriteTool`/`FileListTool`/`_validate_path`；`Tier`/`Confirmer` 从 `task.py` 移入并泛化；`ToolContext` 新增 `tier`/`allowed_root` 字段；`default_registry()` 注册全部新工具
- [x] `src/forgeagent/protocol.py` — 新增 `WebFetchArgs`/`FileReadArgs`/`FileWriteArgs`/`FileListArgs`
- [x] `src/forgeagent/task.py` — `allowed_root` 解析并同步传给 executor 后端与 `ToolContext`（防止两者漂移）
- [x] `src/forgeagent/cli.py` — `_accumulate_usage`/`_print_usage`；`run_once()`/`repl()` 会话级用量累加与打印
- [x] `tests/test_ssrf_guard.py` — 新增，IP 矩阵（含 NAT64/IPv4-mapped）+ 逐跳复检 + scheme 拒绝 + `_create_connection` 遮蔽回归
- [x] `tests/test_web_file_tools.py` — 新增，WebFetch 成功/掩码/SSRF 失败/确认门（拒绝/批准/trusted 跳过）+ File 读写列表的成功/越权拦截/确认门/相对路径覆盖
- [x] `tests/test_tools.py` — 更新 `default_registry` 断言以覆盖全部 7 个内置工具
- [x] `tests/test_anthropic_client.py` / `tests/test_openai_compatible_client.py` — 扩展 `_fake_reply` 支持缓存字段 + 新增 `cached_tokens` 断言（存在/缺失两种情形）
- [x] `tests/test_cli.py` — 新增单任务多轮累加、REPL 跨任务累加测试
- [x] `docs/threat-model.md` — 新增 T10a（WebFetch SSRF）/T10b（FileWrite 越权写）/T10c（FileRead 泄露 secret）行 + T10a 与 T3 的边界差异说明
- [x] `docs/golden-tasks-seed.md` — G321-G340（20 个，配比精确维持），总数扩到 340

## 三次评审

### 技术方案评审

- [x] 12 项裁决逐一对照实现代码确认落地，无方案偏离
- [x] Phase-0 spike 发现的 `_create_connection` 遮蔽 bug 在设计阶段即修正,最终代码采用 `__init__` 内实例属性覆盖（非类属性），已通过专项回归测试验证
- [x] WebFetch 确认门（真实安全边界）与 FileWrite 确认门（UX 层）的区分在代码注释与 threat-model 文档中均如实标注，未发现过度承诺或误导性描述

### 代码评审

- [x] 环境暂无 `code-reviewer` 类型 subagent；改为亲自逐一读取全部落地源码（`ssrf_guard.py`/`tools.py`/`protocol.py`/`cli.py`/两个 LLM client）+ 针对性 PoC 验证最高风险假设（重定向到 `file://` 是否绕过 SSRF Guard 的 scheme 检查）
- [x] PoC 结论：不存在绕过——`urllib.request.HTTPRedirectHandler` 自身拒绝非 http(s) 跳转目标（`HTTPError: Redirection ... is not allowed`），与 WebFetch 前置 scheme 校验构成双重防护
- [x] 未发现其他真实缺陷：`_validate_path` 的 realpath 前缀校验、`mask_secrets` 调用点（WebFetch 落盘前+返回前、FileRead 返回前）、`FileList` 相对路径转换、两个 LLM client 的防御性 `getattr` 链、CLI 累加器对 `usage=None` 轮次的跳过逻辑，均按设计正确落地
- [x] 5 个并行 subagent 之间出现一次 git 竟态：Phase 1（token usage 映射）与 Phase 2（SSRF Guard）几乎同时 `git add`+`git commit`，导致 Phase 2 新建的 `ssrf_guard.py`/`test_ssrf_guard.py` 被一并卷入 Phase 1 的提交 `f342153`。两部分内容本身均正确、互不覆盖，只是提交边界与提交信息不完全对应实际 diff；未 push，功能无损，决定不做历史重写（rebase 属于破坏性操作且当时仍有其他并行提交在发生），如实记录在此
- [x] 无遗留未处理发现

### 验收评审

- [x] ACTION_PLAN M10 行"验证"列（—，自定义证据）：全量单测 + ruff 满足：
  ```
  $ .venv/bin/pytest tests/ -q
  350 passed, 11 skipped in 25-30s
  $ .venv/bin/ruff check src/ tests/
  All checks passed!
  ```
  （11 个 skip 均为既有跨里程碑 skip：docker 依赖/Windows-only 分支，与本里程碑无关）
- [x] ACTION_PLAN M10 行"门禁"列（视需求排期，弱门禁）：满足。golden 集扩到 340（`grep -oE '\bG[0-9]+\b' docs/golden-tasks-seed.md | sort -u -V | wc -l` = 340），配比核对 136/85/68/34/17 = 40/25/20/10/5% 精确匹配
- [x] 12 项设计裁决全部落地，`restricted`/`container` 档下 WebFetch/FileWrite 确认门断言生效（`tests/test_web_file_tools.py`）
- [x] 无未满足项

## 遗留问题

- [ ] Phase 1/Phase 2 提交 `f342153` 的边界因并行 git 竟态与实际语义不完全对应（提交信息只描述 token usage 映射，实际 diff 还包含完整的 SSRF Guard 模块）— 影响：仅提交历史可读性,功能与测试均验证正确、无实质代码问题 — 计划：不做处理（未 push，rebase 属破坏性操作,收益不足以承担风险；未来若需要拆分可在后续不相关的整理性提交中一并处理）
- [ ] WebFetch 目前仅验证了本地 mock HTTP 服务器场景与真实公网抓取（设计阶段 spike），未做大规模真实站点冒烟 — 影响：极少数使用非标准 content-type 或异常大响应头的站点行为未覆盖 — 计划：留待真实使用中观察，不阻塞 M10 收尾
- [ ] M9（流式/多模态/内嵌指令）仍处于顺延状态，未开始 — 影响：无（用户裁决顺延，非取消）— 计划：M10 完成后按 ACTION_PLAN 排期补做

## 续接指引

M10 已完成：新增用量可观测性（`TokenUsage.cached_tokens` 跨两个 LLM client 落地 + CLI 会话级用量状态行）与工具生态扩展（`WebFetchTool` 经 SSRF Guard 收窄出网面 + `FileReadTool`/`FileWriteTool`/`FileListTool` 经 `_validate_path` 锁定 project-root）。`ToolContext` 新增 `tier`/`allowed_root` 字段，`Tier`/`Confirmer` 类型从 `task.py` 迁移并泛化至 `tools.py`，为后续任何新的确认门式工具（下一个可能是 MCP 之外的第三方 API 调用）提供了无需改类型别名的扩展点。

安全模型上最重要的新增认知：WebFetch 的确认门是当前唯一真实拦截出网的机制（restricted/container 档下 Exec 已全拒出网），FileWrite 的确认门只是 UX 提示——这一区分已写入代码注释与 `docs/threat-model.md` T10a-T10c，后续若新增任何"主进程 Tool 绕过 executor 沙箱直接触达敏感资源"的工具，都需要先问一遍"这个确认门是否是唯一防线"，避免重复 FileWrite 式的过度承诺。

本里程碑首次尝试"5 个 subagent 并行开发同一里程碑"的协作模式：4 个 agent（Phase 1/2/5/6）分别touch 互不重叠的文件集，1 个 agent（Phase 3+4 合并）承接共享文件集，规避了并行编辑冲突；但仍发生一次 git-add/git-commit 竟态导致两个 agent 的提交边界重叠（遗留问题已记录）。未来若再用此模式，可考虑让每个并行 agent 使用独立的 git worktree（`Agent` 工具的 `isolation: "worktree"` 选项）来完全消除这类竟态,但要权衡额外的磁盘/时间开销。

M10 延续的约束：零新依赖（本里程碑全部新代码仅用标准库）；隔离强度声明保持诚实（WebFetch/FileWrite 的确认门边界差异同样遵循这一原则，不做"看起来全面但实际不然"的承诺）；三轮评审机制（含代码评审,本次因无可用 code-reviewer 类型改为亲自读码 + 针对性 PoC）在每里程碑收尾执行。

下一步：按 ACTION_PLAN 里程碑表回到 **M9 流式 + 多模态 + 内嵌指令**（`ModelClient.stream()`/`StreamEvent`、`ContentItem` 联合类型、`/model`/`/search`/`/mcp`/`/help` 内嵌指令，golden 任务集虽任务扩展）——用户 2026-07-11 裁决顺延而非取消，M10 完成后应补做。

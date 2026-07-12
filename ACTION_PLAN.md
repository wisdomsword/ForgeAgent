# ForgeAgent 行动计划（v2 — 已终审，2026-07-07 用户认可）

> 最高宪法：`spec.md`。本计划已终审通过；M1–M8 已完成。**用户裁决（2026-07-11）**：M9（流式/多模态/内嵌指令）顺延，跳过直接进 M10（用量可观测性 + WebFetch/File 工具生态 + SSRF 收敛）；M9 未取消，待 M10 完成后补做。
> 终审状态：M0 计划评审 ✅、M1 设计 ✅（六份设计文档 + `docs/m1-consistency-check.md`）、M2 地基 ✅（数据模型/能力登记/MockClient/协议解析器/Anthropic client + capability-gating/配置加载）、M3 执行环路 ✅（utils 运行时/trusted executor 后端/Step 循环/Task 循环/mock replay 端到端/golden 扩到 30，G01/G05/G13 反馈环闭合）、M4 策略约束 ✅（AST 策略引擎含 T7 动态导入/restricted 子进程后端 audithook+rlimit+超时+spawn 拦截/默认 restricted 档/T1-T7 逃逸测试全断言被拦）、M5 CLI + 验收 ✅（CLI REPL+单次命令+smoke/安全配置装配 LLM_API_KEY 优先/golden 扩到 80/README 完成，173 单测全绿；真实模型冒烟在 ANTHROPIC_* profile 上 sonnet-5/haiku-4-5 各 4/4 通过，**用户已认可 M5 通过**）。**已知后续项**：冒烟中偶发模型不遵循系统提示词的角色设定、以"Kiro"自称并用纯 prose 回答而非文本协议，导致该轮 `no_feedback`——不阻塞 M5，留待后续观察是否需要提示词加固。M6 OpenAI-compatible client 实现与真实冒烟验证已完成（gpt-5.4-mini/glm-5.2/deepseek-v4-flash 三个真实厂商端到端跑通；233 单测全绿，ruff 清；`model_registry.py` 精确 model_id→group 路由替换了原固定优先级扫描机制），三轮自评审与里程碑文件收尾完成（见 `milestones/milestone_006.md`）。M7 工具插件化 + MCP + Survey + Registry 完善已完成：设计文档 `docs/m7-tools-mcp-survey.md`（8 项裁决 + Phase-0 `mcp` SDK wire spike 9/9 通过）；`ToolRegistry` 可插拔工具集（Exec/Edit/Survey/MCP）、Survey 内联 question+可注入 asker（headless→need_info）、MCPManager 多 server 常驻后台 loop + 并发建连 + 每 server 失败隔离 + per-(server,tool) 确认门（官方 `mcp` SDK stdio）、`ModelRegistry` alias O(1) 索引 + reload + list_models、golden 扩到 300（G01–G300 唯一 ID 精确核对，配比 40/25/20/10/5% 精确达标），298 单测全绿 + 1 skip、ruff 清；Phase-6 对抗性代码评审发现并修复 5 个真实 bug（`close()` 子进程泄漏、`enable()` 空操作、MCP 结果未 secret 掩码、env 继承不一致、崩溃 server 未标记 unavailable）；三轮评审与里程碑文件收尾完成（见 `milestones/milestone_007.md`）。**用户验证追加**：真实第三方 MCP server（npx `@modelcontextprotocol/server-filesystem` + docker `ghcr.io/github/github-mcp-server`）端到端冒烟通过，过程中修正了用户 `~/.forgeagent/mcp.yaml` 里一个真实配置 bug（github server 环境变量名应为 `GITHUB_PERSONAL_ACCESS_TOKEN`，非 `GITHUB_TOKEN`）。M8 container sandbox（OS 级隔离）已完成：设计文档 `docs/m8-container-sandbox.md`（9 项裁决，1-8 按建议通过 + 用户追加第 9 项"`/proc`/`/sys` 信息暴露适当防御" + Phase-0 spike D1-D9 全部真机实测，非模拟）；新增 `ContainerBackend` 执行档，复用 `restricted` 档完全相同的 worker JSON 协议，隔离手段换成 OS 级 mount namespace + docker 加固标志集（`--network none --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp --tmpfs /sys:ro --pids-limit`），路径透明挂载（`allowed_root` 同路径挂载），缺 docker 时显式报错绝不静默降级；`--tier container` + `--container-image` CLI 接线；golden 扩到 320（G301-320，配比 40/25/20/10/5% 精确维持），313 单测全绿 + 1 个既有 skip、ruff 清；对抗性代码评审发现并修复 7 个问题（2 major：未信任 worker stdout 解析崩溃风险、`ContainerBackend.close()` 未调用致资源泄漏；3 minor + 2 nit）；三轮评审与里程碑文件收尾完成（见 `milestones/milestone_008.md`）。**已知残留风险（诚实声明,非阻塞）**：`/proc/cpuinfo`/`meminfo`/`version`/`net/*` 等基础信息因 runc 禁止 `/proc` 内部自定义挂载而无法遮蔽,作为指纹级风险保留（T9b）；container 档仅在本机 Docker Desktop(linux-aarch64) 上实测，未验证 Linux 原生 docker/podman 兼容性。M10 用量可观测性 + WebFetch/File 工具生态扩展已完成：设计文档 `docs/m10-usage-observability-and-tools.md`（12 项裁决 + Phase-0 spike 发现并修正 `_create_connection` 类属性覆盖被遮蔽的 bug）；新增 `TokenUsage.cached_tokens`（两个 LLM client 均映射）+ CLI 会话级用量状态行；新增 `ssrf_guard.py`（`_create_connection` hook 逐候选校验 + NAT64 解包 + 直连已校验 sockaddr 堵 DNS-rebinding TOCTOU + 借 `HTTPRedirectHandler` 天然逐跳复检）与 `WebFetchTool`/`FileReadTool`/`FileWriteTool`/`FileListTool`（`_validate_path` project-root 锁定，`restricted`/`container` 档下 WebFetch 确认门是真实安全边界、FileWrite 确认门仅 UX 提示——二者边界差异已写入 `docs/threat-model.md` T10a-T10c）；本里程碑首次采用 5 个 subagent 并行开发（4 个独立文件集 + 1 个合并共享文件集），过程中发生一次 git-add/commit 竟态（Phase 1/2 提交边界重叠，内容均验证正确，未 push、决定不重写历史）；代码评审因无可用 `code-reviewer` 类型改为亲自读码 + PoC 实测（验证 SSRF Guard 无 `file://` 重定向绕过，`urllib.request.HTTPRedirectHandler` 自身即拒绝非 http(s) 跳转目标）；golden 扩到 340（G321-340，配比 40/25/20/10/5% 精确维持），350 单测全绿 + 11 skip、ruff 清；三轮评审与里程碑文件收尾完成（见 `milestones/milestone_010.md`）。M9（流式/多模态/内嵌指令）仍处于用户裁决的顺延状态，未取消，M10 完成后应按排期补做。
> 调研基础：已通读 agent 核心执行链路（taskmgr → task/step → response 解析 → toolcalls → executor → runtime）、LLM 客户端层、提示词模板、配置与测试。

## 一、结论

**需要 harness 体系，但拆成两层轻量 harness，而不是一个大框架：**

- **运行时 harness**（ForgeAgent 产品的组成部分，随包分发）：系统提示词模板、Python code rules 强约束引擎、sandbox 分级、行为边界。四者彼此咬合——提示词声明协议，规则引擎强制协议，验证集检验协议，行为边界兜底越界——不成体系会各自漂移。
- **开发 harness**（约束开发过程，纯 markdown，不引入工具链）：CLAUDE.md（已建）、设计文档模板、code review 清单、subagent 任务模板、golden 验证集清单。

避免 harness 本身长成第二个项目：开发侧每项都是单页文件。

## 二、调研结论（已完成，实证）

| agent 机制 | 判定 | 理由 |
|---|---|---|
| 文本协议：`<!-- Block-Start -->` 代码块 + `<!-- ToolCall -->` 标记（`response.py`） | **借鉴** | 不依赖厂商 function-calling API，天然模型无关——接 gpt-5.5 / GLM-5.2 / DeepSeek 零适配 |
| Step 反馈环：LLM→解析→执行→结果回喂→循环（`step.py`） | **借鉴** | 整个 code-as-action 范式的心脏，实现简洁 |
| AST 规则引擎：检查+自动修复+生成 LLM 反馈（`code_analyzer.py`） | **借鉴并扩展** | 就是"python code rules 强约束"的现成雏形，规则可插拔 |
| `utils` 运行时：`set_state()` 结构化回报、跨块状态、运行时装包（`runtime.py`） | **借鉴** | 让执行结果机器可读，是反馈质量的关键 |
| LLM 客户端抽象：统一重试/退避/错误消息（`llm/base.py`） | **借鉴简化** | 保留 openai 兼容基类 + claude 原生两条线即可 |
| Jinja2 组合式提示词（`res/prompts/*.j2`） | **借鉴** | 提示词=可测试的配置文件，而非硬编码字符串 |
| 上下文压缩 4 策略（`context.py`） | **简化借鉴** | 轻量版先只要 sliding window，预留策略接口 |
| Edit 工具（old/new 替换生成新版本块） | **借鉴** | 避免整块重发，省 token |
| trustoken 全链路、`diagnose.py` 上报、更新检查 | **不借鉴** | 硬编码厂商端点；`res/default.toml` 甚至硬编码了一个上报 api_key（已核实） |
| GUI / IPython 模式 / 插件市场 / i18n / "AI牛马"人设 | **不借鉴** | 与轻量定位冲突 |
| 同进程裸 `exec()` 无隔离（`exec/python/executor.py:88`） | **不借鉴，重设计** | 安全缺口，sandbox 是 ForgeAgent 相对原项目的主要增量 |
| 命名风格（`prun.py`/`mod_dict.py`/`taskmgr` 等） | **不借鉴** | 全部换为描述性英文命名，M1 出命名对照表 |

## 三、七项设定逐项判定

| 用户列的设定 | 是否需要 | 归属 | 形态 |
|---|---|---|---|
| 1. 项目系统提示词 | **需要** | 运行时 harness | `prompts/` 模板文件：角色+输出协议+Python 环境+工作流，组合式。（开发侧的"系统提示词"已存在 = spec.md + CLAUDE.md，不再新建） |
| 2. 方案设计提示词 | **需要，但降级** | 开发 harness | 不需要独立提示词体系；一页设计文档模板（问题/约束/方案/否决项/验证方式），M1 起每里程碑一份 |
| 3. 验证方案规则和验证集 | **需要** | 两层都有 | 开发层：pytest 单测 + **mock LLM 回放测试**（录制的 LLM 响应喂进执行环路，无 key 也能端到端测）；产品层：**golden 任务集**（10–20 个可自动判分的真实任务）跑真实模型 |
| 4. Python code rules 强约束 | **需要** | 运行时 harness | AST 规则引擎（借鉴 code_analyzer 架构）：禁导入/禁调用/路径与网络约束，规则随 sandbox 档位联动、可配置。开发期另用 ruff + 类型检查 |
| 5. Code review 原则 | **需要** | 开发 harness | 一页 checklist：命名可读性/无硬编码/最小范围/安全边界/测试覆盖，每里程碑收尾自审，可叠加 /code-review |
| 6. Subagent 任务模板 | **需要** | 开发 harness | 一页模板：上下文包+目标+强约束+验收标准+返回格式。边界：subagent 只做编码与测试，不做架构决策（呼应 spec.md 的算力分配原则）。**返回格式固定字段**：改动摘要 / 测试结果（原样输出）/ 未验证项 / 偏离计划项 / 需要主 Agent 决策项——五项缺一不可，呼应 spec.md 的"实证汇报" |
| 7. 行为边界设定 | **需要** | 运行时 harness 为主 | sandbox 分级 + 不可逆操作确认门 + secret 掩码（借鉴 env 掩码并扩展）+ 文件/网络策略，全部配置驱动 |

## 四、里程碑（每个都有交付物、验证方式、门禁）

| 里程碑             | 交付物                                                                                                                                                                                                                                                          | 验证                                           | 门禁             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------- | -------------- |
| **M0 计划评审**（当前） | 本文件 + CLAUDE.md                                                                                                                                                                                                                                              | —                                            | **用户批准后才进 M1** |
| **M1 设计**       | 威胁模型；模型客户端契约；15 个 seed golden tasks；模型 capability matrix；文本协议 spec；subagent 任务模板                                                                                                                                                                             | 设计自洽性对照 spec.md 逐条检查                         | **用户评审设计文档**   |
| **M2 地基**       | Anthropic 原生 client；MockClient；协议解析器；配置加载；多模型配置支持（claude-fable-5 / claude-opus-4-8 / claude-sonnet-5 / claude-haiku-4-5）。**不做**：OpenAI-compatible client、复杂 multi-model orchestrator                                                                         | 单测（解析器含畸形输入/JSON 修复用例）                       | 自审 + 实证汇报      |
| **M3 执行环路**     | Task/Step 循环；mock replay 端到端；最小 Python executor；seed golden tasks 扩到 30 个                                                                                                                                                                                    | mock LLM 回放测试端到端跑通                           | 自审 + 实证汇报      |
| **M4 策略约束**     | AST policy；restricted 默认档位；escape tests；文档明确 restricted 是防误操作层、不是真安全隔离，恶意代码必须走未来 container                                                                                                                                                                   | **逃逸用例测试**：受限档位下读 secret / 越权写文件 / 违规出网必须被拦截 | 自审 + 实证汇报      |
| **M5 CLI + 验收** | REPL；单次命令执行；golden 任务集扩到 80 个；claude-sonnet-5 / claude-haiku-4-5 真实模型跑通；Fable 5 opt-in smoke test；README                                                                                                                                                     | 验证集通过率报告（原样贴输出）                              | **用户验收**       |
| **M6**          | OpenAI-compatible client；golden 任务集扩到 200 个；                                                                                                                                                                                                                 | —                                            | 视需求排期          |
| **M7**          | 工具集:MCP/Survey实现;能力登记 YAML + `ModelRegistry`（alias/reload）进一步完善；**工具插件化**（`ToolRegistry`）；golden 任务集扩到 300 个以上；                                                                                                                                              |                                              | 视需求排期          |
| **M8**          | container sandbox（OS 级隔离）；golden 任务集虽任务扩展；                                                                                                                                                                                                                   | —                                            | 视需求排期          |
| **M9**          | **流式支持**（`ModelClient.stream()` + `StreamEvent`）；**多模态消息**（`ContentItem`/`TextItem`/`ImageItem` 联合类型）；内嵌指令包括但不限于：支持内嵌指令/model 可以列出可用模型并且支持切换；支持内嵌指令/search 可以搜索网络资源；支持/mcp显示可用MCP服务，并告知如何使用；支持/help显示可用命令或者详细帮助；golden 任务集虽任务扩展；                             | —                                            | 视需求排期          |
| **M10**         | 用量/计费可观测性：支持CI最下面的状态栏，显示当前状态，token使用量(input, output, cached,etx)等，以及images等多模态使用情况（后续增加声音和视频）；golden 任务集虽任务扩展；工具生态扩展(WebFetch + FileRead/FileWrite/FileList，SSRF 逐跳复检 + project-root 锁定，零新依赖)，在 `restricted`模式下，WebFetch 和 FileWrite 必须触发确认门；FileRead 可记录日志。 | —                                            | 视需求排期          |
|                 | HTTP                                                                                                                                                                                                                                                         |                                              |                |
|                 |                                                                                                                                                                                                                                                              |                                              |                |

编码型子任务按 spec.md 原则派发给低算力 subagent，模板见 M1 交付的 subagent 任务模板。

## 五、技术选型建议（M1 最终确认）

Python ≥3.11 + uv；pydantic v2；openai SDK（一个兼容层覆盖 gpt-5.5/GLM-5.2/DeepSeek 等）+ anthropic SDK（claude 原生）；jinja2 提示词；rich 终端输出；pytest + ruff。**首版不引入**：dynaconf、loguru、fastapi、mcp、插件系统（协议层预留扩展点）。

## 六、开放问题裁决（2026-07-07，用户已裁决，本计划据此定稿）

1. **Sandbox 默认档位**：三档 `trusted` / **`restricted`（默认）** / 预留 `container`。**接受**。
2. **CLI 形态**：首版只做 **REPL + 单次命令执行**，不做 HTTP 服务（HTTP 会引入鉴权/并发/任务状态/日志持久化，首版不碰）。**同意**。
3. **命名**：待定，候选 `forgeagent` / `fa`；发布前查 PyPI 与本机命令冲突，M1 定案。
4. **语言**：代码/注释/内部协议英文；用户文档**中文优先**。
5. **Golden 验证集配比**：40% 文件/数据处理、25% Python 执行与 sandbox 边界、20% 代码修改/小型重构、10% 网络抓取或外部 API（**优先 mock**）、5% 系统查询/环境检查。真实 API key 仅作 **opt-in 验收**（M5 的 Fable 5 smoke test 等），不作为基础 CI 依赖；基础测试必须无 key 可跑（M2/M3 的 MockClient + mock replay 承担这一职责）。

### M1 阶段追加裁决（2026-07-07，设计评审中定，据此进 M2）

6. **B1 运行时 SubTask**：v1 运行时协议**只保留 `Exec`/`Edit` 两个工具**，砍掉 SubTask（运行时子任务委托）。15 个 seed golden task 无一需要。运行时 `SubTask` 与开发期 `subagent-task-template.md` 是两回事，后者属开发 harness、不进运行时协议。将来运行时若需委托，单独定义纯文本 `result` 返回语义，不复用开发期五字段模板。详见 `docs/text-protocol-spec.md`。
7. **B2 执行模型**：executor 抽象后端接口，**按档位挂不同后端**——`trusted`=同进程 `exec()`、`restricted`=每块新起子进程、`container`=容器（**M8 已实装**）。档位语义即隔离强度，人类选档即选执行机制。详见 `docs/threat-model.md`。
8. **B2 跨平台锐化**：restricted 用**每块新起子进程**（非常驻），跨块状态由主进程持 state dict 序列化注入/回收（仅可 pickle 值，文件落盘天然跨块共享——相对 agent 全 globals 持久的有意语义缩减）。隔离机制**统一走跨平台应用层**（realpath 路径白名单 + 默认禁网络模块导入 + `rlimit`[Unix] + 超时 SIGKILL），**不用 Linux-only 的 namespace/unshare/chroot/seccomp**（OS 级隔离已由 container 档实装，见 M8）。**restricted 是跨平台应用层限权，不是 OS 级隔离**——这修订了原 M4 行"restricted 仅防误操作层"的表述（见下方对 M4 行的更正）。
9. **网络与 Broker**：restricted 下网络**默认全拒**；联网 Broker（主进程代理出站 + 逐请求策略 + 日志）留待"需要真联网"时做，v1 不实现，架构已留位。
10. **Y1/Y2 客户端契约**：`complete()` 用显式 `GenerationParams`（非 `**kwargs`），capability-gating 翻译规则收敛在 client 内（Haiku 丢 effort/thinking、Fable 不显式传 thinking、max_output 取各模型上限）；`thinking` 为三态 `on/off/auto`（off 非硬保证）；错误用 `ClientError.kind` 枚举（非 retryable 布尔）；refusal 是成功响应 `AssistantMessage(stop_reason="refusal")`、不入错误枚举；`RetryPolicy` 挂 `ClientConfig.retry`；补 `TokenUsage`、`timeout_seconds`、system 消息抽顶层参数。详见 `docs/model-client-contract.md`。
11. **Y3 协议**：代码块用**变长 fence**（借 agent `response.py:24`，防代码内嵌三反引号）；Exec 语言 v1 **仅 Python**（enum 保留，加语言只扩枚举）。
12. **Y4 + 种子集规模**：golden set 是产品级功能验收、非安全套件；T1-T7 系统性逃逸验证归 M4 escape tests，种子集只保留 G06/G14 两个安全冒烟。**种子集扩至 15 个**（用户授权 10–20、不必超 20），维持 §六.5 配比，新增含错误反馈环（G13）这一核心机制覆盖。详见 `docs/golden-tasks-seed.md`。

> **对上方 M1/M4 里程碑行的更正**（保持台账一致）：
> - M1 行"10 个 seed golden tasks" → 实际交付 **15 个**（裁决 12）。
> - M4 行"文档明确 restricted 是防误操作层、不是真安全隔离" → 已被裁决 8 取代为："restricted 是跨平台应用层限权，能挡绝大多数越权 + 一部分蓄意逃逸，但非 OS 级隔离、非密封沙箱；有意绕过应用层的攻击（ctypes/内核漏洞）超出 restricted 范围，归 container 档（M8 已实装）"。M4 escape tests 断言的是**应用层限权拦截**，不是 OS 层拦截。

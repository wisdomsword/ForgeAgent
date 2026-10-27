# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 最高宪法

`spec.md` 是本项目的最高宪法，必须严格执行。核心要求：结论先行、立即行动、实证汇报（未验证的说未验证、测试失败原样贴输出）、最小范围（不做要求以外的功能/重构/抽象）、说到做到（执行完再终止）。编码任务优先考虑交给低算力模型的 subagent。

## 项目使命

重写一个轻量级 Agent，命名为 **ForgeAgent**，借鉴 `resource/agent/`（只读参考项目，不要修改它）的思路：LLM 把任务目标写成 Python 程序，通过执行程序完成任务（code-as-action）。

硬性约束：
- 命名清晰、人类可读，符合 Anthropic 开源项目通用规则（英文代码、描述性命名，禁止 `prun`/`mod_dict`/`taskmgr` 这类缩写）。
- 不硬编码任何厂商端点/API key。参考项目中的 trustoken MAAS 平台、`diagnose.py` 的上报地址与 key（见 `resource/agent/agent/res/default.toml`）明确**不借鉴**。
- 接入通用大模型，配置驱动。目标模型：claude-sonnet-5、gpt-5.5、GLM-5.2、DeepSeek v4 flash 等。
- Sandbox 机制需要考虑且可配置（参考项目完全没有：Python 代码直接在宿主进程 `exec()`）。
- 轻量优先：架构简洁、执行快，靠模型本身能力提升智能，不堆功能。

## 当前状态与流程

项目已有可运行的 ForgeAgent 实现、uv 构建系统与完整测试环路（`src/forgeagent/`，uv + Python ≥3.11 + hatchling）；已完成的里程碑、跳过的编号和最新测试数字以 `ACTION_PLAN.md` 与 `milestones/latest` 指向的文件为准，不得把规划文档中的待办描述当作当前状态。`ACTION_PLAN.md` 与 `TECH_PATH.md` 中未完成的条目均为历史存档。新的开发任务须先更新技术规划并经用户评审批准，再通过 Comet 创建新 change——不要跳过这一步。

参考项目自带测试（进入 `resource/agent/` 安装依赖后 `pytest tests/unit -v`），仅用于验证对参考实现的理解，不属于本项目开发环路。

本仓库已建 CodeGraph 索引（`.codegraph/`），查代码优先用 `codegraph_explore`。索引覆盖 `src/`、`tests/`、`scripts/`、`openspec/` 与 agent 配置目录（`.agents/`、`.claude/`、`.codex/` 等）；**不覆盖 `resource/agent` 参考项目与 `docs/`**，查这两处请用 `git grep`。

里程碑收尾时按 `MILESTONE_GUIDE.md` 规范产出 `milestones/milestone_NNN.md`，并更新 `milestones/latest`。新会话应优先读取 `milestones/latest` 指向的文件的"续接指引"一节，再决定是否需要回溯更早的里程碑文件。

## 本项目开发期遵循以下自动化执行边界

**✅ 无需确认直接执行**
- 依赖管理：`uv` 所有操作（安装/更新/锁定依赖）
- 编译产物清理：删除 `__pycache__`/`*.pyc`/`.pytest_cache`/`.coverage`/`*.log`/`.ruff_cache` 等临时文件
- 代码质量工具：`ruff check`/`ruff format`/`mypy`（含自动修复）
- 测试执行：`pytest`（含覆盖率报告）
- 只读查询：`git log`/`git diff`/`git status`、`ls`/`find`/`grep`、`which python`/`pip list`
- Git 暂存与提交：`git add` + `git commit`（commit message 由 AI 生成，遵循 conventional commits）
- 项目内非源码文件操作：创建/修改/删除 `docs/`、`tests/data/`、临时脚本；`mkdir`/`cp`/`mv` 限项目内
- 网络只读：`curl`/`wget` 下载文件到项目内（**不执行下载内容**）
- source所有操作

**⚠️ 需用户确认**
- 删除源代码文件（`src/`、`forgeagent/` 下的 `.py` 文件）
- 删除配置/数据文件（`*.toml`/`*.yaml`/`*.json`、测试 fixtures）
- `git push`（任何分支、任何远程）
- 修改环境变量（`export`/`unset` 在当前 shell）
- 权限操作（`chmod`/`chown`）
- 操作项目外路径（如 `~/.config`、`/usr/local`）
- 下载后立即执行模式（`curl ... | bash`、`wget -O- | sh`）

**🚫 拒绝执行**
- `rm -rf /` 或 `rm -rf ~` （如果需要执行这个指令，打印出来让我自己执行）
- 修改系统配置（`/etc/*`、`/Library/*`）
- `git push --force` 或 `--force-with-lease`

**适用边界**
- 所有文件系统操作默认限定在项目根目录 `/Users/dragon/Code/ForgeAgent/` 内
- 本策略约束**开发期 AI 行为**，不影响 ForgeAgent 产品运行时的 sandbox 策略（后者见 `docs/threat-model.md`）

## 参考项目 agent 的大图（读多个文件才能拼出的部分）

核心执行环路（Task → Plan → Code → Execute → Feedback）：

1. `agent/taskmgr.py` `TaskManager` 组装一切（LLM ClientManager、RoleManager、插件、MCP），`new_task()` 产出 `Task`。
2. `agent/task.py` `Task.run()` 建立系统提示（Jinja2 组合）并创建 `Step`；`agent/step.py` `Step.run()` 是真正的循环：请求 LLM → 解析 → 执行工具调用 → 把结果渲染成 system feedback 作为下一轮输入 → 直到无 feedback 或 max_rounds。
3. 解析在 `agent/response.py`：LLM 输出是 Markdown，代码块用 HTML 注释标记 `<!-- Block-Start: {"name":...,"path":...} -->`，工具调用用 `<!-- ToolCall: {"id","name","input"} -->`。**这套文本协议不依赖厂商 function-calling API，是模型无关性的关键**。
4. 代码块进 `agent/blocks.py` `CodeBlocks`（命名 + 版本化 + 落盘）；工具调用进 `agent/toolcalls.py` `ToolCallProcessor`（Exec/Edit/MCP/SubTask/Survey，pydantic 校验）。Edit 工具做 old/new 字符串替换生成新版本块，Exec 按名执行。
5. 执行经 `exec/executor.py` `BlockExecutor` 按语言分发：Python 走 `exec/python/executor.py`（**同进程 `exec()`**，globals 跨块持久、注入 `utils` 运行时对象、捕获 stdout/stderr、结果里掩码 env 值）；bash/node/applescript 等走 `exec/prun.py` subprocess（30s 超时）。
6. 执行前 `exec/python/code_analyzer.py` 做 AST 规则引擎：检查 + 自动修复（如删除被禁 import）+ 生成给 LLM 的反馈。规则可扩展（Rule 子类）——这是值得借鉴的强约束机制雏形。
7. `utils` 运行时（`exec/python/runtime.py` + `agent/runtime.py`）：`set_state(success=...)` 结构化回报结果、`get_block_state` 跨块取态、`ensure_packages` 运行时 pip 装包、`get_env` 按声明取密钥。
8. LLM 层 `llm/`：`base.py` `BaseClient`（统一重试/退避/ErrorMessage）→ `base_openai.py` OpenAI 兼容基类 + `client_claude.py` 等；`models.yaml` 模型能力注册表。
9. 上下文管理 `agent/context.py`：sliding window / importance / summary / hybrid 四种压缩策略。
10. 提示词全部是 `res/prompts/*.j2` 模板，由 `default.j2` 组合（role/output/tools/workflow/client/tips）；角色定义在 `res/roles/*.toml`（含 feature 开关）。

三种入口：`cli_task.py` 交互 REPL、`cli_python.py` IPython 模式、`cli_agent.py` FastAPI headless 服务（`agent_taskmgr.py` 线程池并发）。

## 借鉴判定速查

值得借鉴：文本协议（Block/ToolCall 标记）、Step/Round 反馈环、AST 规则引擎、`utils` 运行时状态机制、LLM 客户端抽象与重试、Jinja2 组合式提示词、上下文压缩（简化版）、env 掩码。

不借鉴：trustoken 全链路（`agent/trustoken.py`、`TrustClient`、wizard）、`diagnose.py` 硬编码上报、更新检查、i18n `T()`、GUI/IPython 模式、"AI牛马"人设提示词、插件市场式复杂度。

<comet-ambient-resume>
<!-- Managed by Comet. Edits inside this block may be replaced by comet init/update. -->
<!-- Contract: comet.resume_probe.v2 -->

## Comet Ambient Resume

在这个仓库中，开始处理需要改动或调查的任务前，如果可能存在活跃 Comet workflow，把当前用户请求传入只读探针：`comet resume-probe . --stdin --json`。

- 如果用户通过宿主明确调用任意 Comet Skill（例如 `@comet`、`/comet`、`@comet-native` 或 `/comet-hotfix`），显式调用优先于本恢复协议；不要运行 resume probe，直接进入被调用的 Skill。
- 如果用户通过宿主明确调用的是非 Comet 的 Skill 或斜杠命令，任务意图已由该调用明确：不要运行 resume probe，直接执行该 Skill。
- 如果你正在 Comet 流程内（包括正在等待用户回复你在流程中提出的问题），不要运行 resume probe；把这类回复（例如方案/选项选择）当作当前 change 的继续，直接按用户的选择推进。
- 只信任返回的 `workflow`、`skill` 和 `entrySource`；它们只由项目配置或无配置兼容回退决定。不得扫描或切换另一套 workflow。
- 如果 probe 返回 `auto_resume`，简短说明选中的 active change，并进入 `nextCommand` 指向的永久入口。不要把状态命令当作恢复入口直接推进。
- 如果 probe 返回 `ask_user`，只问一个简短问题并等待用户回复。
- 如果当前请求未明确调用 Comet Skill，且 probe 返回 `out_of_scope` 或 `none`，不要进入 Comet workflow。
- `out_of_scope` 或 `none` 只表示不要因为这个新请求进入 Comet workflow；它绝不表示要暂停或退出一个已在进行的 Comet 流程。
- 如果配置或状态无效且没有 `nextCommand`，停止并报告原因；不要猜测另一个 workflow。
- 不能只因为存在 active change 就把无关任务挂到该 change。Native 的未提交改动由 Native 入口检查，不由探针自动归因。
</comet-ambient-resume>

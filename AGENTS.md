# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 最高宪法

`spec.md` 是本项目的最高宪法，必须严格执行。核心要求：结论先行、立即行动、实证汇报（未验证的说未验证、测试失败原样贴输出）、最小范围（不做要求以外的功能/重构/抽象）、说到做到（执行完再终止）。编码任务优先考虑交给低算力模型的 subagent。

## 项目使命

重写一个轻量级 Agent，命名为 **ForgeAgent**，借鉴 `resource/agent/`（只读参考项目，不要修改它）的思路：LLM 把任务目标写成 Python 程序，通过执行程序完成任务（code-as-action）。

硬性约束：
- 命名清晰、人类可读，符合 Anthropic 开源项目通用规则（英文代码、描述性命名，禁止 `prun`/`mod_dict`/`taskmgr` 这类缩写）。
- 不硬编码任何厂商端点/API key。参考项目中的 trustoken MAAS 平台、`diagnose.py` 的上报地址与 key（见 `resource/agent/agent/res/default.toml`）明确**不借鉴**。
- 接入通用大模型，配置驱动。目标模型：Codex-sonnet-5、gpt-5.5、GLM-5.2、DeepSeek v4 flash 等。
- Sandbox 机制需要考虑且可配置（参考项目完全没有：Python 代码直接在宿主进程 `exec()`）。
- 轻量优先：架构简洁、执行快，靠模型本身能力提升智能，不堆功能。

## 当前状态与流程

项目处于**规划阶段**：尚无 ForgeAgent 代码，无构建系统（技术选型以批准后的 `ACTION_PLAN.md` 为准，倾向 uv + Python ≥3.11）。行动计划见 `ACTION_PLAN.md`，须经用户评审批准后才能开始方案设计和编码——不要跳过这一步。

参考项目自带测试（进入 `resource/agent/` 安装依赖后 `pytest tests/unit -v`），仅用于验证对参考实现的理解，不属于本项目开发环路。

本仓库已建 CodeGraph 索引（`.codegraph/`），查代码优先用 `codegraph_explore`，覆盖 `resource/agent` 全部源码。

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
- 所有文件系统操作默认限定在项目根目录 `/Users/admin/Code/llm-agent/ForgeAgent/` 内
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

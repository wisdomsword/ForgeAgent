---
comet_change: skills-runtime
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-23-skills-runtime
status: final
---

# M19 Skills Runtime 技术设计

## 1. 设计基线

OpenSpec delta 是需求事实源：

- `openspec/changes/skills-runtime/specs/skills-runtime/spec.md`
- `openspec/changes/skills-runtime/specs/repl-interactive-input/spec.md`

M18 已把程序性 Memory 候选拒绝为 `procedure_requires_Skill`；M19 只补足显式、人工维护的 Skill 生命周期，不自动生成 Skill。M15 的项目输入摘要确认、M16 的 headless 装配、M17 的稳定提示前缀与有界反馈、M18 的项目根信任边界继续有效。

### 1.1 成功标准

1. 用户级和可信项目级 Skill 能被确定性发现，可信项目版本同名覆盖用户版本。
2. 初始系统提示只含 Skill 名称和 trigger，全文必须通过 `Skill` 工具才进入下一轮上下文。
3. 无效、越界、不可读、超限和未知 Skill 都以固定诊断或工具失败收敛，不中断其他 Skill 或宿主进程。
4. CLI 与 HTTP 均可使用不可变 Skill 快照；HTTP 无交互时只复用已有摘要批准。
5. 交互式 REPL 在输入 `/` 时实时显示并过滤指令，可键盘选择；上下键回放当前会话历史。
6. 没有 Skill 目录、显式注入 reader 或非 TTY 时，现有行为保持等价。

### 1.2 明确不做

- 不从 Memory/历史/模型输出自动创建、更新或推荐写入 Skill。
- 不做市场、包分发、依赖解析、版本选择、远程下载或独立意图识别器。
- 不解析并执行一套宿主工作流 VM；steps 仍由模型调用现有工具完成。
- 不增加 `/skills` 管理命令，不持久化 REPL 输入历史。

## 2. `SKILL.md` 契约

每个 Skill 只允许以下布局：

```markdown
archived-with: 2026-07-23-skills-runtime
status: final
---
name: review-python
trigger: Use when reviewing Python changes before completion.
archived-with: 2026-07-23-skills-runtime
status: final
---

## Steps

1. Inspect the diff and affected call paths.
2. Run focused tests.

## Failure branches

- If tests fail, report the exact failure and stop completion.

## Completion criteria

- Findings are resolved or explicitly reported.
- Focused tests pass.
```

规则：

- 路径是 `<skills-root>/<name>/SKILL.md`，只扫描 skills root 的直接子目录。
- front matter 键集合必须恰好为 `name`、`trigger`；`name` 匹配 `^[a-z0-9][a-z0-9-]{0,63}$` 且等于目录名。
- `trigger` 去除首尾空白后为一行 1–240 字符，拒绝换行、控制字符和空内容。
- 三个二级标题大小写与顺序固定，各出现一次且正文非空；其他三级及以下标题可存在。
- 单个原始文件上限 32 KiB，最多保留 64 个 Skill，最终目录提示上限 16 KiB。
- 读取后先按现有 secret policy 掩码，再保存到运行时定义；任何进入确认摘要、提示词、工具反馈或诊断的文本均使用掩码版本。
- 格式失败只输出 `skill ignored: <reason> (<bounded-name>)` 一类固定诊断，不回显正文、绝对路径或异常消息。

选择严格结构是为了让“可版本化、可评审、可测试”成为真实契约。自由 Markdown 的启发式解析会使 trigger 与失败分支边界不可验证，五个纯标题又让元数据目录提取变得冗余；YAML front matter 加三段正文是最小可用格式。

## 3. Skills 核心模块

新增 `src/forgeagent/skills.py`，只包含以下职责。

### 3.1 数据结构

```python
@dataclass(frozen=True)
class SkillDefinition:
    name: str
    trigger: str
    steps: str
    failure_branches: str
    completion_criteria: str
    source: Literal["user", "project"]

class SkillRegistry:
    @classmethod
    def load(
        cls,
        *,
        home: str,
        allowed_root: str,
        confirmer: IdentityConfirmer | None = None,
        allow_project: bool = True,
        trust_record_path: str | None = None,
        diagnostic: Callable[[str], None] | None = None,
    ) -> SkillRegistry: ...

    def catalog_prompt(self) -> str: ...
    def read(self, name: str, section: str = "full") -> str | None: ...
```

Registry 构造完成后不暴露可变映射。reload 构建新的 Registry，成功后才替换会话引用；不在旧对象上增量修改。

### 3.2 路径与扫描

- 用户 root：`<home>/.forgeagent/skills`；项目 root：`<allowed_root>/.forgeagent/skills`。
- 对 root、直接子目录和 `SKILL.md` 都使用 `realpath + commonpath + lstat`，拒绝 dangling link、非目录项、非普通文件和逃逸对应 root 的 symlink。
- 缺失 root 是空集合；root 存在但形状不安全时整级跳过并给固定诊断。
- 目录项按名称排序读取。用户集合先进入合并映射；只有整个项目快照获信后，项目集合才覆盖同名项。
- 超过 64 个或目录字节上限时按最终名称顺序保留可容纳前缀并发出一次固定截断诊断，确保相同输入得到相同目录。

### 3.3 项目摘要与信任

项目候选先完成路径和结构校验，再以 `name + NUL + raw bytes` 的长度前缀序列计算 domain-separated raw digest；以 `name + NUL + masked content` 同样计算 effective digest。摘要确认只展示每个有效项目 Skill 的 `name — trigger`，总长限制为 8 KiB，超出后明确标记 truncation；批准始终绑定完整双摘要。

`identity.py` 新增最小通用 helper：

```python
def resolve_project_content_trust(
    *,
    allowed_root: str,
    raw_content_digest: str,
    effective_input_digest: str,
    trust_record_path: str,
    confirmer: IdentityConfirmer | None,
    summary: str,
    diagnostic: IdentityDiagnostic | None,
    diagnostic_prefix: str,
) -> bool: ...
```

它复用现有 canonical project id、v1 trust record 严格校验、digest match、同目录临时文件和 `os.replace`。`resolve_project_trust()` 改为调用该 helper，但对 `identity-trust.json` 的 schema、确认文本、无内容快路和返回值保持不变。Skills 使用独立的 `~/.forgeagent/skills-trust.json`，避免 identity 与 Skills 摘要互相覆盖。

信任状态：

- 记录双摘要完全匹配：无需 confirmer，项目快照可用，适用于 HTTP。
- 不匹配且 confirmer 批准：当前进程可用；记录可安全更新时持久化。
- confirmer 缺失/拒绝：项目快照不可用，用户集合保留。
- trust record 不可用：输出固定诊断；即使用户本次批准，也只在当前进程内生效且不覆盖异常记录。
- `--no-identity`：`allow_project=False`，不读取或确认项目 Skills；用户 Skills 仍可用。

## 4. 渐进加载与工具反馈

### 4.1 初始目录

`SkillRegistry.catalog_prompt()` 在有 Skill 时生成：

```text
## Available Skills

Choose a skill when its trigger matches the task. Read it with the Skill tool before following it.
- review-python — Use when reviewing Python changes before completion.
```

名称排序固定；无 Skill 返回空字符串。`Task` 新增可选 `skills: SkillRegistry | None`。`Task._build_system_prompt()` 的顺序为：identity/protocol/Memory 基础 → Skills 目录 → MCP 工具目录。每部分缺失时不产生额外空段。该顺序使同一 CLI/HTTP 快照内保持稳定前缀，且 Skill 全文不会污染首轮或 prompt cache。

### 4.2 只读 `Skill` 工具

`protocol.py` 新增：

```python
class SkillArgs(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    section: Literal[
        "full", "steps", "failure_branches", "completion_criteria"
    ] = "full"
```

`tools.py` 新增 `SkillTool`：

- `name = "Skill"`，`risk_level = "low"`，构造时持有不可变 Registry。
- 有效名称返回请求的完整文档或单段，并设置 `truncation_mode="head"`。full 结果设置 continuation，明确列出可用 section；因此 M17 截断时模型能按段重读，而不是把不完整前缀当作全部。
- 未知名称返回 `success=False` 与固定 `Skill is unavailable`，不列绝对路径、不回显未信任名称集合。
- 不接收路径，不读取构造后发生变化的文件，不需要 confirmer。

`default_registry()` 增加 `skills: SkillRegistry | None` 参数，仅在目录非空时注册 `SkillTool`。`Step` 和 `Task` 透传同一 Registry；`SkillTool` 自身不需要扩展 `ToolContext`。protocol parser 继续只从 ToolRegistry 的 `arg_schemas()` 识别工具，因此没有 Skills 时模型即使伪造 `Skill` 调用也得到现有 unknown-tool 解析反馈。

完整 Skill 内容作为普通 tool outcome 经 M17 的 secret masking 和 feedback limit 进入下一轮。32 KiB 单文件上限仍可能高于配置的单结果限额，此时现有截断协议明确告诉模型结果不完整，并指导按 `steps`、`failure_branches`、`completion_criteria` 分段重读；本变更不绕过该预算。

### 4.3 失败分支与完成语义

宿主不解释 `steps` 或 `failure_branches`。模型读到全文后调用 Exec/Edit/File/MCP 等现有工具；工具失败仍成为下一轮反馈，模型同时能从上一轮 Skill tool outcome 获得失败分支声明，并选择停止或降级。

Skill 的 completion criteria 只是模型检查表，不能直接设置 `completed=true`。现有“工具同轮反馈优先、后续轮才可完成”的两阶段规则、确认门和 sandbox 不变。这样既兑现失败分支语义，又不引入不可验证的第二状态机。

## 5. CLI 与 HTTP 生命周期

### 5.1 单次 CLI 与 REPL

新增 `_load_skill_registry()` 小 helper，使用现有 `IdentityTrustRequest`/diagnostic 形状，并增加 `make_console_skill_confirmer()` 以显示“trust project Skills”及“load these project Skills?”，避免复用 identity confirmer 时错误提及 AGENTS.md/MEMORY.md：

1. 解析 `allowed_root` 和 `home`。
2. 加载用户 Skills。
3. 若 `no_identity` 为 false，使用 Skill 专用 confirmer 解析并确认项目 Skill 摘要；否则只保留用户 Skills。
4. 把 Registry 传给 `run_once()`，再传给 `Task`。

REPL 在会话启动时加载一次。`/reload` 先重载 models/context/identity/Memory，再构建 candidate SkillRegistry；任何配置级异常都保留旧 Registry。项目 Skill 被拒绝不是 reload 失败，而是 candidate 中只保留用户集合。成功后一次替换 `current_registry/current_context/identity/memory/skills` 相关引用，避免一半新一半旧。

单次 `forgeagent run` 的默认 stdin 不是确认通道时，项目 Skill 只有已有摘要批准才生效；否则与 HTTP 一样降级。

### 5.2 HTTP

HTTP service 启动时在主线程构建一个 SkillRegistry 快照，复用启动时 resolved home/root 和 `no_identity`。TaskFactory 闭包把同一只读 Registry 传给每个新 Task；Task/Step 只读定义且工具没有执行状态，所以请求间不共享可变 Skill 状态。服务不监视文件变化；变更需重启服务，符合现有配置快照语义。

项目 Skill 未预批准时不阻塞服务启动，只输出固定诊断并使用用户集合。HTTP 不增加 API 字段、动态 reload endpoint 或 per-request Skill 选择。

## 6. REPL 增强输入

### 6.1 reader 选择

`repl()` 把 `read_line` 默认值从绑定的 `input` 改为 `None`：

- 显式传入 callable：原样使用，绝不创建 PromptSession。
- `read_line is None` 且 `console.is_terminal` 与 `sys.stdin.isatty()` 都为真：创建增强 reader。
- 其他情况：使用内置 `input`。

reader 在创建 asker/confirmer 前完成解析，Survey 与确认对话继续复用同一个 reader，因此方向键编辑在交互确认中也可用，但 slash completer 只对 `/` 开头整行产出候选。

### 6.2 prompt_toolkit 配置

复用 `prompt_toolkit.completion.WordCompleter`：

```python
WordCompleter(
    list(_SLASH_COMMAND_USAGE),
    meta_dict=_SLASH_COMMAND_USAGE,
    sentence=True,
    match_middle=False,
)
```

`PromptSession` 配置 `InMemoryHistory()` 和 `complete_while_typing=True`。`sentence=True` 让 `/m` 只匹配命令前缀，并在命令后出现空格/参数时停止候选；meta 直接来自 `/help` 同一 usage 表。默认键绑定在候选菜单活动时用方向键移动候选，接受后可继续输入参数；无活动候选时上下键遍历当前 Session 历史。

不配置 `FileHistory`，因此进程退出即丢弃历史，避免在 `~/.forgeagent` 新增未经用户要求的任务/secret 持久化面。EOF、KeyboardInterrupt、空输入、`quit`/`exit` 的外层处理保持不变。

### 6.3 依赖

`pyproject.toml` 增加 `prompt-toolkit>=3.0,<4` 并通过 `uv lock` 更新锁文件。它只替代默认交互 reader，不改变 Rich 渲染或 CLI 参数解析。

## 7. 错误、诊断与审计

- Skill 发现诊断只包含固定原因和经过名称正则/转义的相对标识；不打印正文、绝对 home/root 或底层异常。
- trust confirmer 继续转义控制字符并用现有 Rich confirmation UI。摘要预览截断时明确提示批准绑定完整 digest。
- `Skill` tool 的调用由现有通用 tool audit 记录工具名、状态和有界参数；全文只在 tool outcome 内，审计不得新增 content 字段。
- Skill 加载不是安全授权。Skill 内任何动作仍由具体工具和执行后端判断风险。
- 用户级 Skill 属用户配置，默认可信；项目级 Skill 属仓库输入，必须经过摘要批准。两者内容进入模型前都做 secret masking。

## 8. 测试设计

### 8.1 `tests/test_skills.py`

- 有效五段解析；缺 front matter、未知键、重复/乱序/空标题段、非法/不匹配名称、trigger 换行与控制字符。
- 缺失目录、unsafe root、dangling/越界 symlink、非普通文件和不可读文件固定诊断。
- 用户/项目合并、可信覆盖、拒绝后保留用户版本、名称稳定排序。
- 32 KiB、64 项、16 KiB 目录边界与确定性截断。
- raw/effective digest 变化、secret masking、首次确认、拒绝、无 confirmer、预批准、异常 trust record 和原子替换。

### 8.2 协议、工具、Task/Step

- `SkillArgs` 有效/无效输入、full/单段读取和 ToolRegistry 条件注册。
- `SkillTool` 成功、未知名称和不触发 confirmer。
- 首轮 system message 只含 name/trigger，不含步骤唯一标记；模型调用 Skill 后下一轮反馈含全文。
- Skill 后续工具失败仍可修正；Skill completion criteria 不使同轮工具调用直接完成。
- 无 Skills 时 system prompt 与既有基线一致。

### 8.3 CLI/HTTP

- run_once、REPL、HTTP factory 均传入 Registry；HTTP 多 Task 共享只读快照而不共享 Step/Runtime。
- `/reload` 成功替换、失败保留旧快照、项目拒绝降级。
- 显式 reader 不构造 PromptSession；非 TTY fallback 调用 input。
- Completer 对 `/`、`/m`、`/mo` 的候选集合逐步收敛，参数输入不再提示。
- PromptSession 使用 InMemoryHistory、未配置 FileHistory；EOF/KeyboardInterrupt/退出回归测试保持通过。

### 8.4 Golden 与回归

- 新增 M19 golden candidate：有 Skill 时模型先读取并按步骤完成；无 Skill 对照不出现 Skill tool；初始提示体积不含全文唯一标记。
- 不改 verified core manifest 的 20 项内容或标准，运行 `python scripts/run_golden_core.py` 保持 20/20。
- 最终执行受影响 pytest、完整 pytest、`ruff check .`、`ruff format --check .`、OpenSpec strict、`uv build`、`git diff --check`。

## 9. 实施顺序与回滚

1. 先锁住 identity trust 既有测试，再以 TDD 完成 Skills schema/registry/trust。
2. 接入协议、工具、Task/Step 渐进加载并做 mock replay。
3. 接入 CLI/HTTP 生命周期与 reload。
4. 增加 prompt_toolkit 和 REPL 输入测试。
5. 更新 golden、README、协议和威胁模型，完成全量验证与两轮 whole-change 自审。

回滚删除 Skills 装配和 prompt_toolkit 即恢复旧行为；Skill 文件与独立 trust 记录均是惰性数据，不影响旧版本。没有数据库或不可逆迁移。


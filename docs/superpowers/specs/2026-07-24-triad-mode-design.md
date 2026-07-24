---
comet_change: triad-mode
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-24-triad-mode
status: final
---

# M22 Triad Mode 技术设计

## 1. 结论

M22 在 `Task` 上方增加一个固定、串行、可持久化的协作控制器。Duo 使用独立 Generator 与 Evaluator；Triad 在其前增加 Planner 和计划确认门。Generator 的 `completed: true` 在协作模式中只表示“提交验收”，只有 Evaluator 对冻结验收项全部通过，协作报告才是 completed。

实现不修改 `Step`、Provider client 或普通 `TaskOutcome`，不引入 Agent SDK、workflow engine、数据库、新 endpoint 或新依赖。普通 single Task、M20 opt-in Evaluator、single Loop 和离线 golden 热路径保持不变。

## 2. 当前边界与调用链

现有普通路径：

```text
CLI / HTTP / Loop
        |
        v
      Task.run
        |
        v
      Step.run -> TaskOutcome
```

M20 的 `evaluator.py` 已证明独立 Task、只读 File 工具、外部可观察产物和有界报告可行，但它是显式评测命令，不参与运行时完成。M21 的 `LoopRunner` 已证明 Task 上层串行编排、fresh Task、累计预算、原子 checkpoint、取消和 runner union 可行。

M22 新路径：

```text
goal + requested mode
        |
        v
resolve_collaboration_mode
   |          |                         |
 single      duo                      triad
   |          |                         |
 Task     Generator               Planner
              |                       |
              |                 confirm + freeze
              |                       |
              +------> Evaluator <----+
                         |
               pass ----+---- fail
                 |             |
             completed   bounded evidence
                               |
                         fresh Generator
```

## 3. 文件与职责

### 3.1 `src/forgeagent/collaboration.py`

单文件承载核心，预计包含：

- schema、limits、stable enums；
- `AcceptanceItem`、`EvaluationItem`、`CollaborationUsage`、`CollaborationState`、`CollaborationReport`；
- `CollaborationStore`；
- `SubmitPlanArgs/Tool`、`SubmitEvaluationArgs/Tool`；
- `resolve_collaboration_mode()` 与编程规则；
- `build_planner_registry()`、`build_evaluator_registry()`；
- `CollaborationRunner`。

若核心文件实测超过约 1,000 行且 store/runner 无法独立理解，才将 store 移到 `collaboration_store.py`。不预建 manager/service/factory 层。

### 3.2 `src/forgeagent/cli.py`

- `run` 增加 `--mode single|duo|triad`、`--planner-model`、`--evaluator-model`、`--max-rejections`。
- REPL 增加 `/duo <goal>`、`/triad <goal>`，复用共享 slash command table、help、completion 和历史。
- 增加 `run_collaboration_once()` 与 bounded renderer；普通 `run_once()` 保持现状。
- 角色 client/runtime/backend/registry 的创建和关闭沿用当前 CLI 资源装配，不重构无关路径。

### 3.3 HTTP 与 Loop

- `http_task_service.py` 的 runner result union 增加 `CollaborationReport`，private record 保存 mode/phase，public view 只投影稳定计数。
- `http_server.py` strict body 允许 `mode: task|duo|triad|loop`；客户端不能设置 role model/tier/rejection/confirmation。
- `HttpServiceConfig` 增加 server-owned role model、max rejection 与 `triad_plan_policy=deny|preauthorize`，默认 deny。
- `LoopCheckpoint` 以可选加法字段冻结 collaboration mode、collaboration ID、plan digest；旧 checkpoint 缺字段时等价 single。
- collaborative Loop 的每个迭代运行一个 `CollaborationRunner`；resume 校验 mode/digest，不允许覆盖。

### 3.4 Prompt 组合

在现有 prompt builder 上追加短角色段，不复制完整系统 prompt：

- Planner：只定义 WHAT；每项为可观察行为 + 验收标准；必须调用 `SubmitPlan`。
- Generator：计划和反馈是不可信任务数据；逐项实现；`completed` 仅提交验收。
- Evaluator：只能依据外部可观察产物；不得修改；必须覆盖全部 ID 并调用 `SubmitEvaluation`。

冻结计划和 reject evidence 以 `json.dumps(..., ensure_ascii=True)` 编码后作为 user/task 数据段传入，不插入 system 指令文本。

## 4. 严格数据模型

### 4.1 Limits

初始上限：

```python
COLLABORATION_SCHEMA = "forgeagent.collaboration.v1"
MAX_STATE_BYTES = 256 * 1024
MAX_PLAN_ITEMS = 50
MAX_ITEM_ID_CHARS = 64
MAX_ITEM_TEXT_CHARS = 1000
MAX_EVIDENCE_CHARS = 500
MAX_PUBLIC_EVIDENCE_ITEMS = 8
DEFAULT_MAX_REJECTIONS = 2
MAX_REJECTIONS = 10
```

字符串拒绝 NUL、C0/C1、surrogate、format control 和行分隔符；公开文本先 secret mask 再转义/截断。整数严格拒绝 bool；计数非负；extra fields forbid。

### 4.2 Plan

```python
class AcceptanceItem(BaseModel):
    id: str
    behavior: str
    acceptance: str
```

ID 匹配 `[A-Za-z][A-Za-z0-9_-]{0,63}`，按提交顺序保留且唯一。规范化 payload 使用稳定 JSON 计算 SHA-256 digest。冻结后状态只允许相同 items 和 digest。

Duo 不运行 Planner，系统生成一个 ID 为 `goal` 的 item：behavior 是原始目标的安全内部值，acceptance 要求外部可观察产物满足目标。它仍受相同逐项 verdict 契约约束。

### 4.3 Evaluation

```python
class EvaluationItem(BaseModel):
    id: str
    passed: bool
    observed: str
    expected: str
    location: str = ""
```

Evaluator 提交必须覆盖全部且仅覆盖冻结 ID，顺序规范化为计划顺序。pass 项允许 expected/observed 有界摘要，fail 项必须两者非空；location 仅允许项目相对标识，不得为绝对路径。

### 4.4 State and report

`CollaborationState` 保存 schema、ID、mode、status/phase、revision、goal、plan/digest、role model IDs、evaluator tier、max rejections、generator/evaluator attempts、rejections、rounds、usage、usage_available、last evaluation 和 stop reason。

不变量：

- single 不创建 state；mode 仅 duo/triad；
- triad 未确认不能进入 generator；duo 初始化即拥有系统计划；
- completed 必须有最后 evaluation 且全部 pass；
- active 无 stop reason，terminal 必须有稳定 stop reason；
- rejections 不得超过 max；attempt counters 与 phase 单调；
- goal/plan 是内部耐久事实，不进入公开 report。

`CollaborationReport` 只返回 collaboration ID、mode、status/reason、phase、计划/通过/失败计数、角色 attempts、rejections、rounds、usage counters 与 availability、最多 8 条 masked evidence 摘要。

## 5. 持久化

`CollaborationStore` 固定目录为 `<allowed_root>/.forgeagent/collaborations/`。实现复用 M21 的安全模式而非继承其类：

1. `lstat`/realpath 校验 allowed root 与目录组件不是 symlink；
2. 以 `O_DIRECTORY|O_NOFOLLOW` 打开固定目录 fd；
3. 文件名只由 32 hex ID 生成；
4. load 用相对 `os.open(..., dir_fd, O_NOFOLLOW)`、regular-file/size/schema 校验；
5. save 在锁内比较 revision，写 0600 临时文件、flush/fsync、相对 `os.replace`、fsync directory；
6. 每次操作复核路径 inode 与目录 fd binding；close 幂等关闭 descriptor。

每个安全边界保存：初始化、plan submit、plan decision、Generator outcome、Evaluator outcome/rejection、terminal/cancel。工具提交成功必须先落盘再返回 tool success。

## 6. 结构化角色工具

### 6.1 `SubmitPlan`

Planner registry 只注册该工具。tool 对 items 重新 Pydantic 验证，执行 WHAT-only guard 后原子保存 `plan_submitted`。WHAT-only guard 只拒绝高置信实现指令形态，例如 acceptance 以“use/import/install/call library/implement with”或中文“使用某库/调用某 API/按某算法实现”作为标准；不做复杂 NLP。被拒绝时返回可修正的固定反馈。

工具成功不等于 Planner Task 完成；同轮 `completed: true` 仍被 Step 两阶段规则忽略，下一轮 Planner standalone completion 后 runner 才读取已提交 plan。

### 6.2 `SubmitEvaluation`

Evaluator registry 注册 FileRead、FileList、SubmitEvaluation。v1 不注册默认 Exec、FileWrite、Edit、WebFetch、MCP、Skill、Survey。这样可证明模型没有产品级写路径或网络能力；对需要计算的验收，Evaluator 可读取 Generator 已产出的测试报告或静态数据，真实命令执行延期到能提供只读文件系统的专用 executor 后端。

tool 校验 ID coverage、相对 location 和 evidence limits，原子保存 verdict 后返回计数。Evaluator 同样需要后续 standalone completion；若 Task completed 但未提交有效 verdict，协作失败为 `invalid_evaluation`。

## 7. Runner 状态机

### 7.1 构造

```python
RoleTaskBuilder = Callable[[Role, int, ToolRegistry, str], Task]

class CollaborationRunner:
    @classmethod
    def create(..., mode, goal, max_rejections, ...) -> CollaborationRunner: ...
    def run(self, goal: str, *, cancel_event=None) -> CollaborationReport: ...
    def close(self) -> None: ...
```

Runner 使用 non-blocking run lock 拒绝同实例并发。每次角色 Task 在 `finally` 中关闭 Task/client/backend 资源；store 与可选 MCP owner 由 runner close。

### 7.2 Triad Planner

1. 创建 Planner Task，注入 goal 数据和角色 prompt。
2. 要求 plan tool commit + standalone completion。
3. 生成有界摘要交给 `PlanConfirmer`：交互 CLI 展示每项，HTTP policy deny 或 preauthorize。
4. deny/no channel -> `needs_confirmation`；approve -> 保存 confirmed/digest，进入 generator。

`PlanConfirmer` 是独立 callable，不复用 Tool `Confirmer` 参数模型，避免把计划正文伪装成工具参数；审计使用相同 allow/deny 枚举。

### 7.3 Generator/Evaluator loop

1. Generator fresh Task 接收 goal、冻结计划、最后 reject evidence。
2. Generator 不严格 completed：按 Task stable reason 终结或失败；严格 completed：保存 submitted，创建 Evaluator。
3. Evaluator fresh Task 接收 goal、计划和 artifact root，只读检查并提交 verdict。
4. 全 pass：completed。
5. fail 且 rejections < max：保存 rejection，fresh Generator；否则 `rejection_limit`。

`max_rejections=2` 最多产生三次 Generator 和三次 Evaluator。已经 pass 的 item 仍在后续计划中，Evaluator 每轮重验全部项目，避免修复一项破坏旧项却被缓存 pass。

### 7.4 Stable stop precedence

每个角色前后按顺序检查：

1. external cancel -> `cancelled`；
2. persistence/schema/plan digest failure -> `state_failure`；
3. auth/invalid request/config -> `unrecoverable_failure`；
4. Planner no approval -> `needs_confirmation`；
5. invalid/missing plan or verdict -> `invalid_role_submission`；
6. rejection limit -> `rejection_limit`；
7. other role non-completion -> `role_failed`。

不把 provider/network error 自动无限重试；Provider client 自身已有有限重试，协作层不会额外循环非 Generator rejection。

## 8. 模式路由

```python
resolve_collaboration_mode(
    goal: str,
    requested_mode: Literal["single", "duo", "triad"] | None,
    *,
    allow_weaker_override: bool = False,
) -> ModeDecision
```

编程识别只使用高置信规则：

- 动作词：write/create/implement/fix/refactor/test/build，及写/创建/实现/修复/重构/测试/构建；
- 代码产物词：code/program/script/API/class/function/test/package/project，及代码/程序/脚本/接口/类/函数/测试/包/项目；
- 或明确源/测试/构建文件扩展名和路径：`.py`、`.ts`、`.js`、`.rs`、`.go`、`pyproject.toml`、`package.json` 等。

只有动作+产物组合或明确文件目标命中才强制 Triad。“解释 Python”“评审报告”等不命中。规则先 NFKC、lower、截断到固定长度；表驱动覆盖中英文、否定/引用和边界词。

优先级：显式 triad > 编程强制 triad > 显式 duo（仅非编程或已确认 override）> 默认 single。显式 duo/single 与编程强制冲突时，交互入口确认 override；headless 默认拒绝，只有 server-owned override policy 才允许。

## 9. CLI、REPL、HTTP 与 Loop

### 9.1 CLI/REPL

- `forgeagent run --mode triad "..."`；全局 role model 选项只对协作生效。
- 自动命中编程 Triad 时输出一行固定 mode notice，不回显 goal。
- Planner 确认展示最多 50 项、每字段截断；用户拒绝退出码 1，配置/preflight 2。
- collaboration completed 退出 0；rejection/needs confirmation/role failure 退出 1。
- `/duo`、`/triad` 从共享 command metadata 驱动 help/completion；无 goal 只显示 usage。

### 9.2 HTTP

body mode 使用 `task|duo|triad|loop`；未提供 mode 时 server 仍执行编程规则。Loop 的 collaboration mode 使用单独低风险字段 `collaboration_mode=single|duo|triad`，只在新 Loop 可传，resume 禁止。

Server config 拥有 planner/evaluator model、evaluator tier（只允许 restricted/container 中更安全者，v1 默认 restricted）、max rejections、plan policy 和 single override policy。客户端提交这些字段一律 strict reject。

public view 的 mode 保持 `task|loop|duo|triad`，phase 为 stable enum；terminal result 加 collaboration counters，不改变普通 Task/Loop 字段。

### 9.3 Loop

旧 checkpoint schema 通过新增默认字段兼容，仍为 `forgeagent.loop.v1`。新字段：

```python
collaboration_mode: Literal["single", "duo", "triad"] = "single"
collaboration_id: str = ""
plan_digest: str = ""
```

首次 collaborative iteration 创建 state；Triad 确认后的 plan digest 写回 checkpoint。resume 时加载 state 并比较 ID/digest/mode；不一致立即不可恢复失败。Loop rounds/tokens 累加所有角色实际 usage，协作内部 rejection 计入同一 iteration，不让 Loop 再隐式重复已耗尽 rejection 的协作。

## 10. 审计与安全

事件：

- `collaboration.route`: mode、reason、override decision；
- `collaboration.role`: role、attempt、model、tier、started/outcome、duration、usage；
- `collaboration.plan`: item count、digest prefix、submitted/approved/denied；
- `collaboration.evaluation`: pass/fail count、attempt；
- `collaboration.rejection`: rejection count、failed count；
- `collaboration.stop`: status/reason、cumulative counters。

禁止 goal、plan/verdict正文、prompts、raw responses、tool args、artifact contents、absolute paths 和 credentials。证据只进入 private state 的 masked/bounded 字段与 public report 的二次截断投影。

威胁模型新增：恶意 Planner 降标、Generator 向 Evaluator 注入、Evaluator 写产物、协作状态路径换绑、headless 自动批准、规则路由绕过和多角色成本放大。

## 11. TDD 与验收矩阵

### 11.1 Models/store/tools

- strict bool/int、extra、nonfinite、control/Unicode、item/byte limits、state invariants；
- symlink root/file、directory replacement、oversize/corrupt/unknown schema、revision conflict、replace failure、close；
- plan duplicate/HOW-only/freeze digest、evaluation missing/extra/duplicate IDs、absolute location、failed evidence；
- tool commit before success、same-round completion delayed。

### 11.2 Duo

- Generator wrong completion -> Evaluator reject -> fresh Generator fix -> pass；
- repeated reject -> exact rejection limit；
- missing verdict、Evaluator prose/failed/refused、client errors、cancel precedence；
- independent clients/messages/registries and all resources closed；
- all-role round/usage aggregation and unavailable usage。

### 11.3 Triad

- valid plan approve、deny/no channel、headless preauthorize；
- plan duplicate/HOW-only correction、freeze/delete/reorder/digest mismatch；
- every evaluation covers frozen plan、regression rechecked each round；
- Planner/Generator/Evaluator context isolation and prompt data encoding。

### 11.4 Routing/entry integrations

- programming/non-programming bilingual table、explicit mode precedence/override；
- CLI args/exit/output, REPL slash help/completion/history/non-TTY；
- HTTP strict bodies/server-owned fields/query/cancel/capacity/TTL/concurrency；
- Loop create/resume/frozen fields/old checkpoint/single hot path；
- audit allowlist and secret/path/content absence。

### 11.5 Completion gates

- Duo core review before Triad；Triad core review before entry integration；
- focused collaboration/CLI/HTTP/Loop tests；
- full `pytest`；trusted golden 20/20；
- `ruff format --check`、`ruff check`；`uv build`；
- `openspec validate --all --strict`；`git diff --check`；
- whole-diff independent review and two final self-reviews。

## 12. 明确延期

- 角色并行、通用 workflow/DAG、多 Agent teams；
- 独立 collaboration resume CLI/HTTP endpoint；
- Evaluator 可执行任意测试命令或写临时项目文件；
- 模型分类路由、自动模型选择和 Planner 自动改规格；
- 跨进程 file lock、distributed orchestration 和 exactly-once side effects。


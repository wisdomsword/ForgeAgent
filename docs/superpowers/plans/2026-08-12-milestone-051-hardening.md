---
archived-with: 2026-08-12-split-runtime-boundaries
status: final
---
# M51 安全与契约加固实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复或证伪评审清单 S1-S14，补齐存储多进程准入证据，并在行为冻结后按低耦合顺序拆分超大模块。

**Architecture:** 每个信任边界或行为契约使用独立 Comet/OpenSpec change；先完成 P0/P1 安全与可复现基线，再处理反馈和语义，最后才做行为不变拆分。所有修复先写最小失败回归，验证报告分别落盘，里程碑结束时统一跑全量门禁并归档。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest、uv、Ruff、Comet/OpenSpec。

## Global Constraints

- `spec.md` 是最高宪法；结论先行、立即行动、实证汇报、最小范围、说到做到。
- restricted 是应用层限权；runtime prefix 只读以支持 import，写入仅限 `allowed_root`。
- 不新增第三方依赖，不增加 manager/factory/framework 式抽象。
- 直接依赖必须保留明确上界，锁文件必须提交。
- 代码、注释和内部协议使用英文；OpenSpec/Superpowers 工件使用 `zh-CN`。
- 每个原决策点先做两轮自审，再采用推荐方案；不可逆或真实外部风险仍不得越权。
- 测试中已固化的 S2、S7、S8 错误行为必须同步反向修改。
- collaboration/memory 锁在多进程 + SIGKILL 证据完成前只能标记“未知”，不得宣称已确认无问题。
- 结构拆分只能在 characterization tests 和存储准入通过后开始；先纯移动，再做小函数提取。

---

### Task 1: Phase 0 与 restricted 写边界

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/forgeagent/_sandbox_worker.py`
- Modify: `tests/test_collaboration_docs.py`
- Modify: `tests/test_restricted_backend.py`
- Modify: `docs/threat-model.md`
- Create: `openspec/changes/bound-direct-dependency-versions/`
- Create: `openspec/changes/harden-restricted-write-boundary/`

- [x] 删除与 archive 同名且无独有内容的四个僵尸 active change。
- [x] 为全部直接依赖增加主版本兼容上界，运行 `uv lock` 并同步契约测试。
- [x] 写 S1 三条 RED 回归，再让 restricted worker 以 `writes_only_in_root=True` 安装 audit hook。
- [x] 更新 T2/T7 threat model，运行 focused pytest 与 `uv build`。
- [x] 在全量 pytest 绿后完成两个 change 的 verify/pass/archive。

### Task 2: WebFetch 授权键绑定完整有效 URL

**Files:**
- Modify: `src/forgeagent/headless.py`
- Modify: `tests/test_headless.py`
- Modify: WebFetch/redirect 相关测试
- Create: `openspec/changes/harden-webfetch-authorization-scope/`

- [x] 写 RED：相同 path 不同 query 不得共享授权，redirect 每跳重新校验。
- [x] 使用版本化、固定长度的原始 query 摘要；不排序、不持久化明文 query，不接受旧 query-less WebFetch key。
- [x] 验证 key 语法、隐私、重复参数及顺序语义。

### Task 3: 严格配置输入

**Files:**
- Modify: `src/forgeagent/model_registry.py`
- Modify: `src/forgeagent/mcp_manager.py`
- Modify: `src/forgeagent/models.py`
- Modify: `tests/test_model_registry.py`
- Modify: `tests/test_mcp_manager.py`
- Modify: model validation tests
- Create: `openspec/changes/strict-config-validation/`

- [x] 写 RED：未知顶层/叶字段、非 mapping YAML、MCP 布尔字符串/数字、temperature 非有限值。
- [x] 每份 YAML 在 merge 前校验顶层结构与允许键；相关 Pydantic 模型 `extra="forbid"`。
- [x] 仅 `enabled`/`required` 使用 strict bool；temperature 使用 `FiniteFloat`，厂商范围暂不扩公共 capability。
- [x] 对外抛带来源位置的稳定启动错误，不暴露完整 Pydantic 异常。

### Task 4: restricted 资源限额与信号反馈

**Files:**
- Modify: Task/CLI/config/executor 相关模块
- Modify: restricted backend/CLI/config tests
- Create: `openspec/changes/configure-sandbox-resource-limits/`

- [x] 写 RED：restricted timeout/CPU/memory 配置、CLI 覆盖优先级、非法值、SIGXCPU 人类可读原因。
- [x] 新增 restricted 专用限制值对象；优先级为 CLI > 配置 > 现有默认值，不影响 container 配置。
- [x] 对 POSIX 负 returncode 映射稳定信号类别；`SIGKILL` 保持“可能由限额导致”的非过度断言。
- [x] 用有界父进程可见通道保留已产出 stdout/stderr，并在反馈前掩码。

### Task 5: 三项语义一致性

**Files:**
- Modify: Task/CLI/public projection modules and tests
- Modify: `src/forgeagent/model_registry.py`
- Modify: `src/forgeagent/image_input.py`
- Create: 三个独立 OpenSpec change

- [x] S8 引入 `verified_completed` / `answered_unverified` / `stopped` 三态及兼容 bool 投影，逐一更新 CLI/HTTP/Loop/eval/audit 消费方。
- [x] S9 用户显式提供 group `models` 时替换列表；省略时保留基础列表；覆盖空列表和重新分组。
- [x] S7 先 stat，再只读有界头部识别类型；可识别超限图片整体失败，大型非图片继续跳过；目录复用单文件加载逻辑。

### Task 6: TTL、稳定反馈与协议恢复

**Files:**
- Modify: `src/forgeagent/http_action_approvals.py`
- Modify: `src/forgeagent/protocol.py`
- Modify: `src/forgeagent/step.py`
- Modify: `src/forgeagent/transport_errors.py`
- Modify: corresponding tests
- Create: `openspec/changes/harden-error-and-protocol-boundaries/`

- [x] S11 分离 monotonic 到期判定与 wall-clock 展示时间，覆盖时钟前后跳。
- [x] S12 模型反馈只含稳定类别和字段位置；详细异常进入有界、先掩码的 debug 日志。
- [x] S13 用已复现的跨注释吞并输入写 RED；先按完整 HTML comment 边界扫描，再逐个 JSON 解析。
- [x] 运行 parser/Step/provider 聚焦回归，确认后续有效 ToolCall 不被前一畸形标记吞掉。

### Task 7: 存储多进程准入与耐久性

**Files:**
- Create: `tests/test_storage_process_safety.py`
- Modify: `src/forgeagent/memory.py`（仅在 RED 证明耐久性缺口时）
- Create: storage admission OpenSpec change

- [x] 使用 `multiprocessing.get_context("spawn")` 验证 collaboration 同 revision 竞争与 memory 并发更新。
- [x] 确定性 SIGKILL 单独 lock holder，验证内核释放锁及后续正常写；不得宣称证明断电耐久。
- [x] 有界、固定 seed 的随机 writer SIGKILL 只断言无死锁、无损坏和后续可恢复。
- [x] 为 Memory 原子替换补父目录 fsync，并用可执行回归固定与 CollaborationStore 一致的耐久性步骤。

### Task 8: 行为不变结构拆分

**Files:**
- Modify/Create: protocol、step、mcp_manager、collaboration 的内部边界模块
- Modify: characterization tests

- [x] 补协议顺序/畸形 marker/fence/body、Step 终态与 audit 顺序、MCP lifecycle、collaboration store/runner characterization。
- [x] 按 `protocol.py -> step.py -> mcp_manager.py -> collaboration.py` 顺序纯移动，保留公共 facade/re-export。
- [x] 仅在纯移动绿后做小函数提取；C901 先输出报告，不设置为阻塞门禁。
- [x] 每个拆分点运行对应聚焦测试和 diff review，禁止引入新框架式抽象。

### Task 9: M51 最终验证、复审与归档

**Files:**
- Create: `milestones/milestone_051.md`
- Modify: `milestones/latest`
- Modify: `ACTION_PLAN.md`
- Create/Modify: 各 change 验证报告和 archive 目录

- [x] 运行 Ruff、format check、全量 pytest、Golden、`uv build`、全部 active OpenSpec strict。
- [x] 完成两轮全 diff 自审与独立代码审查；发现问题立即修复并重跑覆盖验证。
- [x] 逐个把 verify/pass change 归档并同步主 specs；归档后再次运行 OpenSpec strict 与关键测试。
- [x] 写 M51 交付物、验证证据、遗留风险和续接指引，更新 `milestones/latest` 与 ACTION_PLAN。

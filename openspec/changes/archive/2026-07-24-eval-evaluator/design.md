## 上下文

现有 trusted golden runner 已输出 `forgeagent.golden.v1` JSON 报告，运行时已输出脱敏的 `AuditEvent` JSONL。两者足以支撑 M20 指标，但 schema 有意独立，报告目前也没有历史持久化。20 项 core 是离线 CI 权威；其中 5 项真实模型场景仍然单独 opt-in。

## 目标 / 非目标

**目标：**

- 将 golden 报告与审计事实规范化为确定性的 M20 evaluation record，保存并与上一条记录比较。
- 计算首轮正确率、修正轮数、cache 命中率和 golden 通过率趋势，不解释 prompt、源码或模型 prose。
- 用提交到仓库的 canonical baseline 拒绝 trusted-core manifest 漂移。
- 运行只接收外部契约和产物清单的 opt-in 独立真实模型 Evaluator。

**非目标：**

- 不增加常驻 Evaluator 服务、scheduler、HTTP endpoint、Planner 角色，也不改变普通 Task 完成语义。
- 离线 CI 不发 LLM 请求；不扩充或放宽 20 项 core；不自动更新 manifest baseline；Evaluator 不检查源码树。

## 决策

### Evaluation record 作为窄集成边界

从 golden 报告和可选的 audit JSONL 创建 `forgeagent.evaluation.v1` record。每次运行原子写入一个 JSON 文件，并维护有界索引，仅保留最近记录。聚合模块同时接受路径和纯 mapping，使表驱动测试不需要模型、用户 home 或 CLI。

相比评估数据库/服务，这更符合本地运行与离线 CI；相比把字段塞进 `GoldenSuite`，不会污染原本简洁的测试报告契约。

### 指标缺失时显式不可用

`first_pass_correctness` 是在一轮完成的已完成任务比例；`correction_rounds` 是已完成任务的额外轮数均值。cache 命中率仅在选中的成功 attempt 都有合法分母时按 token 加权计算。golden 通过率直接来自报告的 `passed`/`total`。空输入或不可用输入编码为 `null`，不伪造 `0` 或 `100`。

相比从 LLM 文本推导正确性，这保持了“机械终止”和“事实判断”分离的既有边界。

### Manifest 使用提交内 canonical baseline

Golden manifest 导出覆盖 scenario ID、title 和 real-model eligibility 的有序 fingerprint。仓库内 baseline fixture 保存批准的 20 项和 digest；runner preflight 遇到任意不一致就失败。更新 baseline 必须和 manifest、候选目录一起做显式源码变更，绝不能由 runner 自动写回。

仅检查 ID 集合不足以阻止替换函数或修改 real-model eligibility 后降低标准，因此采用完整 fingerprint。

### Evaluator 是独立、显式 opt-in 的 Task 会话

`evaluate` CLI 只有在用户显式选择配置模型后才解析并调用。它创建新的 Task，并使用专用 evaluator prompt；不带入 Generator conversation、Memory、project Skills 或 audit sink。输入契约只包含验收条件和位于显式 evaluation directory 下的有界相对产物清单。Evaluator 可复用现有只读/执行工具，但结构化结果必须给出观察证据，失败时指出未满足的期望。

相比传递 Generator 的 Task/Step 对象，这不会泄漏上下文；相比新增第二套服务协议，也不会在 M21/M22 前引入另一套编排系统。

## 风险 / 取舍

- [审计字段缺失或过旧] → 保留 `null`，报告跳过/无效事件，不声称有指标。
- [本地趋势记录损坏] → 严格 JSON 校验、有界文件名、原子写入；忽略无效历史并给出固定诊断。
- [产物可能包含 prompt injection] → 产物明确标注为不可信数据；Evaluator 不获得额外权限，且只在显式 opt-in 时运行。
- [LLM Evaluator 非确定] → 不进入 CI，并用已知 fail 注入做确定性检出测试；trusted core 仍由脚本判定。

## 迁移计划

无需迁移。既有 golden JSON 报告仍是合法输入；只有显式评估命令才写新记录。移除该能力时只需删除其专属评估目录，不影响既有运行。

## 未决问题

无。M20 范围和 opt-in 边界已由 `TECH_PATH.md` 与 M19 续接指引确定。

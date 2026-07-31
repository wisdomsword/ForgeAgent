---
comet_change: prompt-memory-rewrite-governance
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-30-prompt-memory-rewrite-governance
status: final
---

# Prompt、Memory 与重写治理门禁技术设计

## 1. 设计结论

本 change 只增加开发期治理，不增加运行时能力。使用一份 canonical Markdown 作为条款事实源，再用确定性的本地测试验证其关键字段；既有 Skill、Memory 和 Prompt 运行时继续由当前实现和专项测试负责。

## 2. 组件与边界

### 2.1 Canonical 文档

`docs/agent-governance-gates.md` 提供三个模板：

1. `Prompt/Skill Exit Contract`：五类退出状态，每类包含 `condition` 与 `verifier`，并记录模型版本、最小回归集和过时 scaffolding 清理。
2. `Memory Governance Review`：谁可写、为什么记、真相来源、失效/复核、可见性/崩溃恢复、删除/更正。
3. `Rewrite / Dependency Gate`：六项指标，每项包含基线、门槛、证据、迁移和回滚触发器。

模板同时写明最小验收、反例和适用边界：只约束新增或实质修改的长期内容，不强制迁移历史文档。

### 2.2 规范引用

`spec.md` 是项目最高宪法，新增一条治理入口；`MILESTONE_GUIDE.md` 在问题卡、设计、实现、验证阶段分别引用对应模板；综合借鉴清单把候选 5 指向 canonical 文档；`docs/threat-model.md` 记录缺少退出证明、记忆来源/可见性不明和无回滚证据的开发期风险。

### 2.3 文档契约测试

`tests/test_governance_docs.py` 使用 `Path` 读取项目内文件，按稳定 Markdown 表格行断言：

- canonical 文档存在并包含五个退出字段，每行有非空 `condition`/`verifier`，并有模型升级字段；
- Memory 四个核心问题、两个安全字段及可见性/恢复和删除/更正；
- 六项 Rewrite 指标，每行有五个证据列；
- canonical 文档、`spec.md`、`MILESTONE_GUIDE.md` 和综合清单都有发布冻结词；
- 测试源码不出现网络、上传、tag、push 调用。

断言失败消息必须包含缺失契约名称，便于文档评审定位。测试不解析 Markdown AST，也不把文档内容注入运行时。

## 3. 数据流

```text
治理条款文档
      │
      ├── spec / milestone / review 引用
      │
      └── 本地契约测试 ──> PASS / 缺失条款名称
```

没有运行时数据流、持久化迁移或外部网络交互。失败只阻止当前 change 的文档验收，不改变 Agent 任务状态。

## 4. 风险与处理

- 文档与代码实现不同步：本 change 只声明流程要求，运行时行为仍由既有测试验证；以后若要自动拒绝不合规 Skill，必须另立 change。
- 模板形式主义：每个字段限制为一句话或证据引用，不增加自动评分器。
- 旧内容不完整：按“新加/实质修改才生效”处理，避免批量迁移。
- 发布误触发：Canonical 文档和契约测试同时锁定暂停措辞，且本 change 不修改发布 change。

## 5. 验证计划

1. 先写并运行失败的 `tests/test_governance_docs.py`。
2. 写 canonical 文档和四处规范引用，重跑专项测试。
3. 执行全量 `pytest`、Ruff check/format、`git diff --check`、OpenSpec strict。
4. 完成两轮最终自评，确认无运行时行为、无 Memory 迁移、无发布动作。


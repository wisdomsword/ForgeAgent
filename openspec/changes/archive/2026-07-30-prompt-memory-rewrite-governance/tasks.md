## 1. 建立治理契约测试

- [x] 1.1 新增 `tests/test_governance_docs.py`，用本地文件读取断言 Prompt/Skill 五类退出条件、Memory 四问、六项 Rewrite 门禁和 PyPI 暂停条款；先运行该文件确认 canonical 文档尚不存在时按预期失败。
- [x] 1.2 为缺失条款提供可定位的断言消息，并断言测试不依赖网络、凭据或发布命令。

## 2. 编写并接入治理规范

- [x] 2.1 新增 `docs/agent-governance-gates.md`，提供长期 Prompt/Skill 退出条件模板、Memory 四问模板、Rewrite/依赖六指标模板和最小验收/反例。
- [x] 2.2 在 `spec.md` 增加治理门禁入口；在 `MILESTONE_GUIDE.md` 增加阶段 1/3/4/5 的引用和检查项，保持原有里程碑结构不变。
- [x] 2.3 在 `docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md` 补充 canonical 文档链接、候选 5 的验收指针和“仅新增/实质修改内容生效”的兼容边界。
- [x] 2.4 在 `docs/threat-model.md` 增加治理漂移/无退出条件/Memory 来源不明/无回滚证据的开发期风险与缓解措施。
- [x] 2.5 在 `ACTION_PLAN.md` 增加 M32 治理门禁里程碑行，记录本地文档契约测试与发布冻结边界。

## 3. 验证与收尾

- [x] 3.1 运行治理专项测试，确认红-绿转换和关键反例覆盖。
- [x] 3.2 运行完整 `pytest`、`uv run ruff check .`、`uv run ruff format --check .`、`git diff --check` 和 `openspec validate --all --strict --no-interactive`。
- [x] 3.3 更新 M32 里程碑与 `milestones/latest`；完成两轮最终自评，明确未修改运行时、未迁移 Memory、未恢复 PyPI，并保持 `publish-v0-1-0` 不推进。

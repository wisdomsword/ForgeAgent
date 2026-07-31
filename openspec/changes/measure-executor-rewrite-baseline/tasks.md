## 1. 测量契约与测试

- [x] 1.1 先新增报告 schema、六项 metric 完整性、脱敏和 verdict 纯判定的失败测试。
- [x] 1.2 新增 trusted/restricted/container 可用性与故障恢复测量边界测试，锁定 `not_available` 不得算通过。

## 2. 离线测量实现

- [x] 2.1 实现标准库 `scripts/m43_executor_rewrite_baseline.py`，采集性能、可靠性、维护、兼容、团队能力和迁移/回滚证据。
- [x] 2.2 运行真实 trusted/restricted 测量；仅在本地 daemon 与固定镜像已可用时测 container，并生成版本化 JSON 原始证据。
- [x] 2.3 根据同口径结果填写六项 baseline、threshold、evidence、migration、rollback trigger 与最终 readiness verdict。

## 3. 文档与规划同步

- [x] 3.1 新增 M43 基线文档，记录原始样本、复现命令、平台边界、阈值判断和未来单模块试验门禁。
- [x] 3.2 更新 canonical 评审/治理文档和 `ACTION_PLAN.md`，明确 M43 只完成测量且不授权重写、新依赖或发布。

## 4. 评审、验证与收尾

- [ ] 4.1 完成两轮 base-ref/文件归因自审，修复模糊、错误、过于保守、前后不一致和遗漏。
- [ ] 4.2 运行聚焦与全量 pytest、Ruff、format、diff check、OpenSpec strict 和 Comet verify，记录未验证的真实边界。
- [ ] 4.3 更新验证报告、`milestones/milestone_043.md` 与 `milestones/latest`，同步主规格并归档 change。

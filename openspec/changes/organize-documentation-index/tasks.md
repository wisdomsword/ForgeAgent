## 1. 文档契约

- [x] 新增 `documentation-index-integrity` 增量规格和精简设计工件。
- [x] 新增索引分区、本地链接、latest 里程碑、完成状态和边界措辞的离线失败测试。

## 2. 当前入口

- [x] 新增 `docs/README.md`，按权威性/生命周期分类并链接当前与历史来源。
- [x] 在根 `README.md` 和 `ACTION_PLAN.md` 增加文档索引链接，不重写历史证据。
- [x] 新增 M46 里程碑收尾记录，验证通过后再更新 `milestones/latest`。

## 3. 验证与生命周期

- [ ] 执行聚焦文档测试、全量 pytest、Ruff、format check、build、OpenSpec strict 和 diff check。
- [ ] 完成两轮自评，记录独立评审，并在验证后归档 change。

## 1. Readiness 与格式契约

- [x] 1.1 先添加失败测试，覆盖无数据、合法 v1、合法 v2、畸形/不安全文件的最小披露 readiness 状态。
- [x] 1.2 定义 v2 record/header、治理元数据、公开结果和固定原因码类型，保持 `MemoryCandidate` 不承载宿主元数据。
- [x] 1.3 实现有界 v1/v2 解析与序列化，分离 storage/render 上限，并保持 v1 load/render 只读兼容。
- [x] 1.4 实现 host API、Task 模型候选和 `/remember` 的固定 source/writer 投影；v1 普通 project 写入返回 `migration_required`。

## 2. 生命周期与受控修改

- [x] 2.1 先添加失败测试，覆盖 expires_at、review_after、可注入时钟以及正文/路径不进入诊断和审计。
- [x] 2.2 实现只投影有效记录的 render，并保留失效记录供治理操作读取。
- [x] 2.3 实现原子纠错、删除和复核操作；每次成功操作生成新 revision 并保持并发 read-modify-write 语义。

## 3. 备份、迁移、验证与回滚

- [x] 3.1 先添加失败测试，覆盖 manifest 缺失/额外 key、symlink 备份、故障注入自动恢复和公开结果脱敏。
- [x] 3.2 实现锁内 v1 重验、完整 manifest 校验、项目内 `0600` 恢复副本和 v2 原子迁移。
- [x] 3.3 实现写后语义 verifier，验证 key/content 等价、元数据完整、revision 与大小边界，并在失败时自动恢复。
- [x] 3.4 先添加失败测试并实现 revision 绑定 rollback；迁移后任意写入必须返回 `rollback_conflict`，不得无条件重放。

## 4. 运维入口与文档

- [x] 4.1 提供仅调用权威 Memory API 的离线 readiness/verify 运维入口，不访问网络、凭据或项目外路径。
- [x] 4.2 更新 runtime Memory 文档、威胁模型和治理说明，明确 v1 只读兼容、manifest 责任、备份位置、回滚冲突和手工纠错边界。
- [x] 4.3 在当前仓库运行 readiness，记录 `no_data`、零条目、未创建备份且迁移跳过的 M42 证据。

## 5. 验证与里程碑收尾

- [ ] 5.1 运行 Memory 专项测试、相关 Task/CLI 集成测试、全量 pytest、Ruff、format、OpenSpec strict、Comet verify 和 `git diff --check`。
- [ ] 5.2 完成两轮代码/契约自评，检查模糊、错误、过度保守、前后不一致、遗漏和公开信息泄漏；发现问题立即修复并重跑相关验证。
- [ ] 5.3 产出 verification report，归档 change，创建 M42 里程碑并更新 `milestones/latest`；不执行 PyPI、tag、push 或发布自动化。

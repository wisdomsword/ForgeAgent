## 1. 证据绑定基础

- [ ] 1.1 为检查临时副本计算与复制规则一致的确定性 Candidate 快照摘要，并补充摘要稳定性、忽略项和错误路径测试
- [ ] 1.2 增加当前 Evaluator Task 私有的检查证据表，按冻结检查 ID、Generator attempt、状态和快照记录最新结果

## 2. Evaluator 完成门

- [ ] 2.1 让 `RunCheck` 写入宿主证据表并只向模型返回既有有界脱敏结果
- [ ] 2.2 让 `SubmitEvaluation` 在全通过 verdict 前验证全部冻结检查均对同一当前 Candidate 通过
- [ ] 2.3 保留失败 verdict 提前提交、无检查兼容和恢复后强制重跑语义
- [ ] 2.4 增加不含命令、路径、输出或摘要的结构化检查审计元数据

## 3. 验证覆盖

- [ ] 3.1 增加未运行、失败、超时、旧 attempt、快照变化、跨检查快照不一致和全部通过场景的工具测试
- [ ] 3.2 增加 Runner 恢复与新 Generator attempt 不复用旧证据的集成测试
- [ ] 3.3 运行目标测试、完整 pytest、ruff、mypy、离线构建和 OpenSpec strict 验证并修复所有失败
- [ ] 3.4 运行 M26 小规模真实 Duo/Triad 验证，保存独立、可复现且不改写 M23/M25 的评测证据

## 4. 里程碑收尾

- [ ] 4.1 更新 M26 直接相关的运行时契约说明和 `ACTION_PLAN.md`
- [ ] 4.2 按 `MILESTONE_GUIDE.md` 生成 M26 记录并更新 `milestones/latest`
- [ ] 4.3 完成代码评审、两轮最终一致性审查、归档 delta spec 和分支收尾

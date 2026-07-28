# Brainstorm Summary

- Change: bind-collaboration-completion-evidence
- Date: 2026-07-28

## 确认的技术方案

采用单次 Evaluator Task 私有的宿主证据表。`build_evaluator_registry` 创建一份共享映射，`RunCheckTool` 写入冻结检查的最新状态、当前 Generator attempt 和实际临时副本摘要，`SubmitEvaluationTool` 只在所有验收项为 pass 时读取并验证该映射。检查 runner 在复制完成、执行开始前计算临时副本摘要；提交时对当前 allowed root 按同一忽略规则重新计算摘要。全部要求检查必须通过、属于当前 attempt、具有同一摘要且摘要仍等于当前 Candidate，才允许保存全通过 verdict。

恢复或新 Generator attempt 会重建空证据表，不持久化旧执行结果。包含失败验收项的 verdict 继续允许提前提交；未配置检查时完全沿用现有行为。

## 关键取舍与风险

不采用持久化证据，因为恢复后无法证明旧进程、旧环境和当前 Candidate 仍一致，且会引入状态 schema 和迁移复杂度。不采用在 `SubmitEvaluation` 内自动执行检查，因为会隐藏成本、阻塞提交并减少模型利用失败反馈的机会。

项目摘要覆盖检查复制规则中的非忽略目录、普通文件路径、类型、权限模式和文件内容，不把 mtime 当作 Candidate 语义。摘要检测正常文件变化并 fail closed，但不声明为对抗宿主级恶意并发写的事务安全边界。摘要不返回模型、不写审计。

Ponytail 检查结果：不新增依赖、配置面、通用 manager/factory 或持久化 schema；仅增加一个领域内摘要函数和一份私有小型证据记录。

## 测试策略

先写失败测试再实现：摘要稳定/变化/忽略项/不安全文件；未运行检查、检查失败、检查间快照变化、检查后 Candidate 变化、当前全部通过；失败 verdict 提前提交；无检查兼容；恢复和新 attempt 证据为空；审计字段不含命令、路径、输出或摘要。随后运行协作目标测试、完整 pytest、ruff、mypy、离线构建、OpenSpec strict 和独立 M26 小规模真实 Duo/Triad 验证。

## Spec Patch

已补充“检查审计不泄露执行内容”场景；无其他范围或需求修改。

# Brainstorm Summary

- Change: enforce-candidate-artifact-readiness
- Date: 2026-07-26

## 确认的技术方案

宿主可选地冻结 `required_candidate_files`。`SubmitCandidateTool` 在执行现有 revision-checked 原子保存前，使用 allowed root 目录描述符确认每个有界顶层名字对应非符号链接普通文件。失败返回当前 Generator Step 可消费的结构化工具反馈，且 phase、attempt、verdict、rejection 均不改变。默认要求为空，现有调用兼容。M22 人类冒烟仅通过私有子进程环境注入 `calc.py` 和 `test_calc.py`。

## 关键取舍与风险

- 保持 `SubmitCandidate` 零载荷，不引入 Generator manifest 或非权威证据。
- 只验证候选载体存在，不读内容、不判语法、不运行测试；Evaluator 继续独占逐项验收。
- 使用 `O_NOFOLLOW`、目录描述符、`fstat` 和 root device/inode 绑定 fail closed；只接受 1-128 字符 ASCII 顶层安全文件名，最多 16 项且不得重复。
- 检查与 Evaluator 之间仍可能发生文件变化，这是既有共享工作目录语义；Evaluator 以实际观察为准。
- 平台缺安全 open flag 时，已配置门禁的提交失败；未配置路径不受影响。

## 测试策略

- TDD 覆盖缺失文件时 SubmitCandidate 失败且状态完全不推进。
- 覆盖普通文件成功、符号链接/目录拒绝、默认空配置兼容、非法/重复配置拒绝。
- 覆盖 CLI 私有 JSON 缺省/合法/非法稳定错误以及 M22 子进程环境注入。
- 运行协作与 CLI 定向测试、完整 pytest、Ruff、build、OpenSpec strict、diff check 和标准代码审查。
- 真实模型一键冒烟继续由用户人工批准 Planner/FileWrite 后执行；自动门禁不消耗模型凭证。

## Spec Patch

已在 delta spec 中增加 `runtime-collaboration` 的宿主 Candidate 文件就绪门 requirement，并修改 `triad-human-smoke` 的一键入口 requirement，明确固定文件要求与人工确认兼容边界。

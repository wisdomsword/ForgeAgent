# fix-generator-rejection-correction 验证报告

## 结论

PASS。3/3 任务完成，修改后的打回环需求与场景有实现和离线回归覆盖；无 CRITICAL 或 IMPORTANT 问题，可以归档。

## 记分卡

| 维度 | 结果 |
|---|---|
| 完整性 | 3/3 tasks；1/1 modified requirement |
| 正确性 | 首轮文件创建约束与 rejection-only 修正提示均覆盖 |
| 一致性 | Candidate、Evaluator、权限、attempt/rejection 预算和 schema 均未改变 |

## 根因与实现映射

- 真实失败现场为 `generator_attempts=3`、`evaluator_attempts=3`、`rejections=2`，但工作目录始终只有 `.forgeagent`，且终端无 FileWrite 确认；Generator 连续提交空 Candidate。
- 通用 Generator prompt 现在明确：要求文件不存在时先成功 FileWrite；文件创建任务中 `SubmitCandidate` 不得是首个或唯一工具调用。
- 仅当 Runner 携带失败 verdict 创建新 Generator Task 时，system prompt 追加 rejection-correction 指令，要求逐项实质修正、禁止原样重提、缺文件先 FileWrite。
- 失败 verdict 仍以有界 JSON task data 传递；没有增加文件活动判定、Candidate payload 或 Generator 自验职责。

## 验证证据

- TDD RED：两个提示契约测试在实现前均按预期失败；补充首个/唯一工具约束时再次 RED 后 GREEN。
- 协作专项：`86 passed`。
- 全量：`2224 passed, 10 skipped`。
- Ruff：目标 3 文件 check 与 format-check 通过。
- 构建：`uv build` 成功生成 wheel 和 sdist。
- OpenSpec：change strict validate 通过。
- 独立复审：无 Critical/Important；1 个非阻塞 Minor 为离线 mock 无法证明真实模型一定遵循提示。

## 残余风险

本修复是提示协议加固，不是文件系统隐式提交门。离线测试能证明正确提示只在正确轮次注入及状态机语义不变，不能证明任意真实模型必然服从。最终行为仍需通过保留人工计划确认的 M22 真实模型冒烟复测；若模型继续无视明确提示，应重新评估 Candidate 门是否需要宿主可验证的不变量，而不是继续叠加提示词。

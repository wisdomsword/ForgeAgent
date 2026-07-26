## ADDED Requirements

### Requirement: 宿主可冻结 Candidate 最小文件就绪门
协作宿主 SHALL 能为一次 Duo/Triad Runner 冻结零个或多个有界的顶层候选文件名。配置非空时，`SubmitCandidate` MUST 在原子状态变更前确认每个名字在 allowed root 下对应非符号链接普通文件；任一文件缺失、类型不安全、无法安全打开或 project root 绑定变化时，提交 MUST 返回结构化失败并保持 phase、Generator attempt、旧 verdict 与 rejection count 不变。该门禁 MUST NOT 读取或判断文件内容，Evaluator 仍独占冻结计划的逐项验收权。未配置文件时 MUST 保持现有 Candidate 提交行为。

#### Scenario: 空 Candidate 被当前 Generator Step 拦截
- **WHEN** 宿主要求 `calc.py` 和 `test_calc.py`，Generator 在两个文件尚未成为 allowed root 下普通文件时调用 `SubmitCandidate`
- **THEN** 工具返回列出缺失安全相对文件名的有界失败，协作保持 generator phase 且 attempt/verdict/rejection 均不改变，当前 Generator 可在剩余轮次调用 `FileWrite` 后重试

#### Scenario: 文件就绪后原子提交
- **WHEN** 所有宿主冻结文件都已是 allowed root 下的非符号链接普通文件，且当前 phase/revision 有效
- **THEN** `SubmitCandidate` 沿用既有原子语义切换到 evaluator phase、递增一次 Generator attempt 并清空旧 verdict

#### Scenario: 符号链接或目录不能满足门禁
- **WHEN** 任一要求名字对应符号链接、目录或 project root 在检查期间发生重绑定
- **THEN** 运行时按 Candidate 未就绪处理且不推进持久状态，不跟随链接读取或泄露宿主路径

#### Scenario: 默认协作路径保持兼容
- **WHEN** single 模式运行，或 Duo/Triad/Loop/HTTP 宿主未配置候选文件要求
- **THEN** 系统不执行额外 Candidate 文件门禁，既有提交、恢复与完成语义保持不变

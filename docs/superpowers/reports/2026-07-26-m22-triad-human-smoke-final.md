# M22 Triad 人类冒烟最终验收报告

## 结论

M22 一键真实模型人类冒烟最终通过。用户在真实 TTY 中人工批准 Planner 计划与两次 restricted `FileWrite` 后，最终运行输出 `M22 TRIAD HUMAN SMOKE: PASS`：冻结计划 8/8 通过，Generator/Evaluator 各 1 attempt，0 rejection。

本报告记录的是结构化提交协议完成后的后续人类冒烟闭环，不替代 [结构化提交验证报告](2026-07-25-collaboration-role-submission-verify.md) 中原有的两次真实 Triad 协议验收。

## 时间线

### 1. 空 Candidate 暴露：首次运行

- Collaboration：`c433416babd444efae89988cc399c1b6`
- 结果：`stopped` / `rejection_limit`
- 计数：Generator 3、Evaluator 3、rejections 2。
- 现场：Evaluator 只看到 `.forgeagent`，`calc.py` 与 `test_calc.py` 均不存在。
- 结论：零载荷 `SubmitCandidate` 缺少宿主可验证的最小产物就绪条件；提示协议不足以阻止模型重复提交空 Candidate。

### 2. 空 Candidate 复现：第二次运行

- Collaboration：`8c98fdc15eba4e22a5511951832b84bb`
- 结果：`stopped` / `rejection_limit`
- 计数：Generator 3、Evaluator 3、rejections 2。
- 现场：再次只有 `.forgeagent`，两份目标文件均不存在。
- 决策：为 M22 子进程冻结 `calc.py`、`test_calc.py` 的非符号链接普通文件就绪门；只检查载体存在性，Evaluator 继续独占内容与正确性验收。
- 修复：`a4f6df3` 至归档提交 `1727d2e`。

### 3. 协作通过但 RunCheck 假失败

- Collaboration：`bd2633c970784ea7929af75eaf2f94aa`
- 协作结果：`completed`，8/8，Generator/Evaluator 各 1 attempt，0 rejection。
- 产物直接复验：`9 passed`；CLI 行为正确。
- 一键脚本结果：FAIL，`pytest check failed with exit code 1`。
- 根因：隔离 check worker 允许读取 Python runtime 文件，却禁止导入器枚举 `sys.prefix`/`sys.base_prefix`，把 `_pytest._code` 误报为缺失；pytest 捕获还需要精确访问 `os.devnull`。
- 决策：仅对 check worker 放行当前 Python runtime 的只读目录枚举与 `os.devnull` 精确路径；普通 restricted executor 和其他宿主目录/设备仍拒绝。
- 修复：`17ce027` 至归档提交 `7438d27`。

### 4. 最终真实 PASS

- Collaboration：`8efdd58913dc4b81a7918502faf23b82`
- 结果：`completed` / `M22 TRIAD HUMAN SMOKE: PASS`。
- 验收：8/8。
- Generator attempts：1。
- Evaluator attempts：1。
- Rejections：0 rejection。
- 人工边界：Planner 计划和两次 restricted `FileWrite` 均由用户显式批准，没有自动确认。
- 最终证据提交：`9835d96`。

## 修复链

1. **Feedback 预算隔离**：子进程固定使用 2000-token 单工具反馈与 4000-token round feedback，避免用户全局 40/120 限额截断 Evaluator 的短文件读取；不修改用户配置、credential 或模型路由。
2. **Candidate 文件就绪门**：`SubmitCandidate` 进入 Evaluator 前验证 M22 冻结的两个顶层名字是 allowed root 下的非符号链接普通文件；不读取内容、不接受模型 manifest、不替代 Evaluator。
3. **RunCheck Python runtime 导入**：只为 check worker 增加当前 Python runtime 目录枚举和 `os.devnull` 精确访问；普通 restricted executor 保持原边界。

## 自动验证

- Candidate 门最终全量：`2247 passed, 10 skipped`。
- RunCheck 热修复最终全量：`2249 passed, 10 skipped`。
- Ruff format/check、sdist+wheel build、Git diff check 均通过。
- 对应 change 归档前 OpenSpec strict 均为 `19/19`；归档后主规格为 `18/18`。
- 安全复审无 Critical/Important finding。

## 口径说明

M22 结构化提交收尾已有两次独立真实模型 Triad 协议验收：一次 7/7 直接通过，一次 8/8 经一次 reject 后修正通过。其后的一键人类冒烟又产生四个可追溯 collaboration，覆盖两次空 Candidate、一次 RunCheck 假失败和一次最终 PASS。因此里程碑应写为“原两次结构化提交协议验收 + 后续四次可追溯人类冒烟”，而不是把不同目的的运行机械合并为“三次”。

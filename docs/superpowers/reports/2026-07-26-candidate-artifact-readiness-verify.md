# Candidate Artifact Readiness 验证报告

## 结论

`enforce-candidate-artifact-readiness` 通过完整验证，可进入归档。未发现 CRITICAL、WARNING 或尚未处理的 IMPORTANT 问题。

## 评分表

| 维度 | 结果 |
| --- | --- |
| 完整性 | 9/9 OpenSpec tasks 完成；2/2 delta requirements 已实现 |
| 正确性 | 7/7 delta scenarios 有实现与自动测试覆盖 |
| 一致性 | 实现符合 OpenSpec design 与技术 Design Doc；无 spec 漂移 |

## 验证证据

- 定向回归：`410 passed`。
- 完整测试：`2247 passed, 10 skipped`。沙箱内 12 个失败均由本地回环端口与嵌套 `uv build` 权限限制导致；同一命令在沙箱外通过。
- Ruff：`105 files already formatted`，`All checks passed!`。
- 构建：成功生成 sdist 与 wheel。
- OpenSpec strict：`19 passed, 0 failed`。
- Git diff check：通过。
- 标准代码审查：首轮发现 root fd 关闭异常可能绕过结构化 fail-closed；已修复并增加关闭失败、FIFO、非法 root、root 重绑定和安全 open flags 回归。复审结论为 `Ready to merge`，无 Critical/Important finding。

## 需求映射

- 可选、默认关闭的 Candidate 文件门：`src/forgeagent/collaboration.py`。
- 缺失或不安全文件不推进 phase/attempt/verdict：`SubmitCandidateTool` 工具测试与 Runner 同 Step 恢复测试。
- 私有 CLI 子进程配置且 single 不受影响：`src/forgeagent/cli.py` 与 CLI 测试。
- M22 固定要求 `calc.py`、`test_calc.py` 且保留原生人工确认：`scripts/m22-triad-human-smoke.py` 与离线脚本测试。

## 人工验证边界

本次自动验证不能外推真实模型一定通过。真实 M22 Triad 仍需用户在真实 TTY 运行：

```bash
uv run --offline python scripts/m22-triad-human-smoke.py
```

运行时继续人工批准 Planner 计划和 restricted `FileWrite`；本 change 未绕过或自动批准这些确认。

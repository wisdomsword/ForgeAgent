---
change: skills-runtime
status: passed
---

# M19 Skills Runtime 验证报告

## 结论

M19 的 12/12 项任务、10/10 项需求和 19/19 个规格场景均有实现与测试证据，
设计、delta spec 和实现一致。未发现 CRITICAL、WARNING 或 SUGGESTION 级遗留项，
change 已完成验证并归档。

## 完整性

| 维度 | 结果 |
| --- | --- |
| Tasks | 12/12 完成 |
| Requirements | 10/10 已实现 |
| Scenarios | 19/19 有覆盖 |
| Design | OpenSpec design 与 Superpowers Design Doc 均已遵循 |

主要映射：

- `src/forgeagent/skills.py` 与 `tests/test_skills.py` 覆盖固定五段结构、确定性发现、
  路径 containment、数量/字节上限、secret masking 和 project-over-user 信任覆盖。
- `src/forgeagent/protocol.py`、`tools.py`、`task.py`、`step.py` 及对应测试覆盖只读
  `Skill` 调用、有界初始目录、下一轮全文反馈、未知名称恢复和既有完成/授权边界。
- `src/forgeagent/cli.py` 与 `tests/test_cli.py` 覆盖 CLI/HTTP 快照隔离、原子 reload、
  逐字符斜杠候选、键盘选择、当前会话上下键历史、非 TTY 与注入 reader 兼容。
- `tests/test_golden_candidates_skills.py` 覆盖渐进加载候选与无 Skill 对照；verified core
  manifest 保持 20 项不变。

## 验证证据

- 最终收尾完整回归 `uv run --offline pytest -q`：
  `1437 passed, 11 skipped in 79.45s`。
- 人类验收专项回归：`15 passed`；用户在真实 PTY 执行
  `uv run --offline python scripts/m19-skills-human-smoke.py`，六项检查全部 PASS。
- `uv run ruff check .`：`All checks passed!`。
- `uv run ruff format --check .`：`82 files already formatted`。
- `uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m19-final-golden`：
  `20/20 passed (100.0%)`。
- `openspec validate skills-runtime --strict`：`Change 'skills-runtime' is valid`。
- `uv build --out-dir /tmp/forgeagent-m19-final-build`：sdist 与 wheel 均成功生成。
- `git diff --check`：通过。
- 最终 `openspec validate --all --strict`：`13 passed, 0 failed`；M19 已归档，后续
  `startup-information` change 在独立 worktree 中继续实施。

## 两轮 whole-change 自审

- 第一轮沿 spec 与调用链复核 `SkillRegistry.load`、`Task`、`Step`、工具注册、CLI/HTTP
  快照和 reload；所有需求均已接线，无遗漏入口。
- 第二轮复核安全与范围：项目 Skill 仍受独立双摘要信任记录约束，诊断、确认和反馈均
  掩码且不泄漏绝对路径；Skill 不提升 tool/sandbox 权限；未加入远程安装、自动生成、
  `/skills` 管理命令、自定义键绑定或持久历史。
- 最终独立代码评审先后发现组合式 secret-feedback 测试缺口和首轮请求省略断言弱化；
  已补回回归测试并重跑全量验证，复审结论为无剩余发现、可合并。

## 分支与残余风险

- 分支处理：verify 阶段按当时决策保留 `codex/skills-runtime`、不推送、不合并；
  完成后的本地人类验收收尾将该归档分支推送至 `origin/codex/skills-runtime`。
  由于后续 `startup-information` change 已在独立 worktree 中活跃，本次不擅自
  合并 `main`。工作区仍含用户既有无关改动，归档提交只纳入 M19 收尾文件。
- user-level Skill 属本地用户配置；project-level Skill 只有显式批准的内容摘要生效。
  Skill 是模型可读指导，不是执行策略，实际安全仍由协议、确认门和 sandbox 保证。

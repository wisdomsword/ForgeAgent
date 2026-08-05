# 验证报告：restore-forgeagent-product-identity

日期：2026-08-05  
提交：`00daa27 fix(identity): restore ForgeAgent product identity`

## 总结

| 维度 | 结果 |
| --- | --- |
| 完整性 | 5/5 tasks，1/1 delta capability |
| 正确性 | 1/1 requirement，3/3 scenarios 有实现和测试证据 |
| 一致性 | 遵循 proposal、design 和 runtime-identity spec |

无 CRITICAL、IMPORTANT 或 WARNING 问题，可进入分支收尾。

## 实现对照

- 固定 system prompt 以 `<system_prompt><role>` 开始，在 [system.j2](../../../src/forgeagent/res/prompts/system.j2) 第 1-27 行明确 ForgeAgent-first 身份、Agent 风格角色段和身份问句前缀要求；没有 native model/provider 身份提示。
- [task.py](../../../src/forgeagent/task.py) 第 79-119 行只识别明确的中英文身份问句，只在 prose 终态且回答没有 ForgeAgent 前缀时替换固定产品说明；已正确前缀的回答、普通问句、工具执行结果不会被改写。调用点在第 390-392 行。
- [default_soul.md](../../../src/forgeagent/res/prompts/default_soul.md)、[protocol.md](../../../src/forgeagent/res/prompts/protocol.md) 和 [m28_release_candidate_smoke.py](../../../scripts/m28_release_candidate_smoke.py) 已同步产品身份和发布标记。

## 场景证据

1. 身份问句：`tests/test_task.py:284` 模拟模型回答 Claude，终态被修复为以“我是 ForgeAgent”开头。
2. 正确性边界：`tests/test_task.py:294` 保留 ForgeAgent-first 回答，`tests/test_task.py:301` 确认普通问句不重写。
3. 提示词隔离：`tests/test_task.py:1309`、`tests/test_task.py:1337` 验证角色段顺序、ForgeAgent-first 文案和 native persona 措辞缺失；`tests/test_identity.py` 验证身份资源契约。

## 验证命令

| 检查 | 结果 |
| --- | --- |
| `uv run pytest -q`（沙箱外，localhost 黑盒测试可用） | `2956 passed, 11 skipped in 157.73s`，退出码 0 |
| `uv run pytest tests/test_identity.py tests/test_task.py tests/test_packaging.py::test_wheel_and_sdist_release_contents -q` | identity/task 通过；打包测试已在可联网环境单独通过 `1 passed in 16.63s` |
| `uv run ruff check .` | `All checks passed!` |
| `openspec validate restore-forgeagent-product-identity --strict` | `Change ... is valid` |
| `git diff --check` / staged diff check | 通过 |
| 真实模型回放 `forgeagent --no-memory --no-identity run "你是谁，你可以做什么？如何做？"` | 终态以“我是 ForgeAgent”开头，未执行工具或程序 |

沙箱内一次打包失败的原始原因是无法解析 `pypi.org` 获取 `hatchling`，并非代码失败；随后在沙箱外完成同一打包测试并通过。完整套件最终在沙箱外通过。

## 人类实际验证

用户连续三次在真实 `forge` 交互中输入同一身份问题，三次结果均以“我是 ForgeAgent”开头：

- 第一次返回简洁的产品能力说明；
- 第二次返回更详细的能力列表和三步工作方式；
- 第三次在缓存命中后再次返回简洁说明。

三次结果均标记为 `answered in prose, not executed`，执行证据均为 `no tools or programs executed`，没有暴露 Claude/Kiro 等底层身份，也没有伪造工具执行结果。这与本 change 的产品身份和 code-as-action 契约一致。

## 安全与审查

本次没有新增依赖、端点、API key 或不受控执行路径。身份边界只作用于显式身份问句的 prose 终态，不接触工具调用、文件系统权限或执行结果。`.comet.yaml` 配置 `review_mode: off`，因此跳过自动代码审查；已完成人工 diff 审读，未发现正确性、安全或边界问题。

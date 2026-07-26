# Brainstorm Summary

- Change: add-m22-triad-human-smoke
- Date: 2026-07-26

## 确认的技术方案

- 使用独立 Python 脚本包装现有 `.venv/bin/forgeagent`，不新增 CLI 子命令或运行时接口。
- 子进程继承当前终端 stdin/stdout/stderr，保留原生 Planner `approve plan? [y/N]` 人工确认。
- 每次创建唯一 `/tmp/forgeagent-m22-human-*` 工作目录，成功和失败都保留。
- 从唯一的 `.forgeagent/collaborations/*.json` 读取稳定状态字段，不解析 Rich 终端文案。
- 依次验证 Triad completed、计划与角色 attempts、`calc.py`/`test_calc.py`、pytest 和 JSON 输出。
- 默认模型通过三个明确环境变量覆盖，不增加通用配置系统，也不打印凭证。

## 关键取舍与风险

- 选择 Python 而不是 Bash，以便可靠解析 JSON、提供离线函数测试并避免 shell 注入。
- 选择包装现有 CLI 而不是新增产品命令，保持 M22 运行时与公开 API 不变。
- 非 TTY 环境在真实模型调用前 fail closed，避免无人工确认通道时产生无效费用。
- ForgeAgent 子进程输出实时继承终端；脚本自身只打印稳定阶段、状态计数和现场路径。
- 默认不删除临时目录，诊断性优先于自动清理。

## 测试策略

- 通过导入脚本并注入 fake subprocess runner，离线覆盖命令组装和控制流。
- 成功 fixture 写入合法 collaboration state、两个产物，并模拟 pytest/CLI 成功。
- 失败矩阵覆盖非 TTY、人工拒绝、ForgeAgent 配置/模型失败、零或多个状态文件、状态异常、
  缺文件、pytest 失败、CLI 非 JSON或数值不匹配。
- 验证 ForgeAgent 调用不设置 stdin/stdout/stderr capture，且测试不访问真实 HOME、网络或凭证。

## Spec Patch

- 为 `triad-human-smoke` 增加非 TTY 场景：无交互终端时必须在调用真实模型前退出并提示人工
  确认不可用。

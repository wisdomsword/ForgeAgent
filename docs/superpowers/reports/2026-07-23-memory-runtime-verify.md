---
change: memory-runtime
status: passed
---

# M18 Memory Runtime 验证报告

## 范围

M18 实现显式 Memory 候选协议、确定性准入、session/project 两级存储、原子项目
持久化、CLI/HTTP 控制、最小披露审计和 golden 候选资产。M15 身份信任边界与
M17 context policy 保持有效；未增加依赖、RAG、向量检索或 Skill 自动写入。

## 验证证据

- `UV_CACHE_DIR=/tmp/forgeagent-m18-uv-cache uv run pytest -q`（升级权限，完整环境）：`1375 passed, 11 skipped`。
- `UV_CACHE_DIR=/tmp/forgeagent-m18-uv-cache uv run ruff check .`：`All checks passed!`。
- `UV_CACHE_DIR=/tmp/forgeagent-m18-uv-cache uv run python -m tests.golden.runner --output-dir /tmp/forgeagent-m18-golden-final`：`20/20 passed (100.0%)`。
- `openspec validate memory-runtime --strict`：`Change 'memory-runtime' is valid`。
- `UV_CACHE_DIR=/tmp/forgeagent-m18-uv-cache uv build --out-dir /tmp/forgeagent-m18-build`：sdist 与 wheel 均成功生成。
- `git diff --check`：通过。

## 两轮终审

- 第一轮检查修复了审计 `kind` 缺失、Memory 路径 symlink 越界、畸形条目诊断、
  render 总量拒绝、失败任务候选落盘和 `--no-identity` 绕过记忆的问题。
- 第二轮检查修复了未获 M15 信任时覆盖既有项目文件，以及 Memory JSON content 内
  `}` 导致正则提前截断的问题；新增对应回归测试并重跑受影响测试。
- 审计不写候选原文；project 文件仅在受信路径内以同目录临时文件加 `os.replace`
  更新；HTTP 每任务独立 manager，不共享 session。

## 残余风险

- 记忆准入使用有限、确定性的注入模式表，不声称覆盖所有自然语言投毒；执行安全仍
  由既有协议、确认门和 sandbox 提供。
- 构建和全量测试依赖临时目录及网络/loopback 权限；本报告使用升级权限完成验证。

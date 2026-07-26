# Check Worker Runtime Imports 验证报告

## 结论

`fix-check-worker-runtime-imports` 通过完整验证，可进入归档。真实 M22 保留现场的生成产物直接运行 `9 passed`，经修复后的 `artifact_failures()` 返回空失败列表。

## 根因与修复

- 根因一：audit hook 允许读取当前 Python 环境文件，却禁止导入器枚举 `sys.prefix`/`sys.base_prefix` 目录，导致 `_pytest._code` 被误报为缺失。
- 根因二：pytest 捕获会打开平台 `os.devnull`，原策略拒绝该精确设备路径。
- 修复：仅 check worker 启用 Python runtime 目录只读枚举和 `os.devnull` 精确路径访问；普通 restricted executor 默认参数为空，其他宿主目录与设备仍拒绝。

## 验证证据

- TDD RED：真实 `python -m pytest -q` RunCheck 稳定失败，stderr 为 `ModuleNotFoundError: No module named '_pytest._code'`。
- 定向测试：`111 passed`；check runner 单项复验 `26 passed`。
- 安全复审：check runner 与 restricted backend 定向 `39 passed`；无 Critical/Important finding，结论 `Ready to merge`。
- 完整测试：`2249 passed, 10 skipped`。
- Ruff：format check 与 lint 通过。
- 构建：sdist 与 wheel 成功。
- OpenSpec strict：归档前 `19 passed, 0 failed`。
- Git diff check：通过。

## 规格一致性

- 5/5 tasks 完成。
- `runtime-collaboration` 的已安装依赖导入、宿主目录继续拒绝场景均有实现与测试。
- 无公共 API、依赖、状态 schema 或普通 restricted 默认行为变更。

## 人工验证边界

旧现场已证明协作与产物正确，并通过修复后的完整 artifact 验收。为取得一键脚本最终 `M22 TRIAD HUMAN SMOKE: PASS` 输出，用户仍需重新运行脚本并完成 Planner/FileWrite 人工确认。

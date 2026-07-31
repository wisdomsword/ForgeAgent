## 1. Golden contract tests

- [x] 1.1 为产物、验证和文本/分析 goal 编写至少三个失败的 Duo golden case。
- [x] 1.2 增加禁止循环验收文案、计划稳定性和不泄漏 goal/path/secret 的回归断言。

## 2. Minimal implementation

- [x] 2.1 用小型确定性分类器重写 `_duo_plan(goal)`，保持单项 `goal` ID 和冻结 digest 契约。
- [x] 2.2 保持旧 snapshot 原样恢复，不引入 LLM 拆解器、依赖或配置。

## 3. Verification

- [x] 3.1 运行 Duo/Collaboration focused pytest、Ruff、format 和 OpenSpec strict。
- [x] 3.2 运行全量 pytest 与 `uv build`，确认不执行 PyPI、tag、push 或发布自动化。
- [x] 3.3 完成两轮自评审并记录 verification report。

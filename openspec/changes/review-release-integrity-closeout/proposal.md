## Why

发布完整性 tweak 已建立最小 sdist 边界，但完成后复审发现测试仍依赖 tar 成员顺序，README 当前验证章节的唯一性检查也可能漏过额外的畸形同名章节；同时当前合同仍与 M22 历史收尾测试耦合，ACTION_PLAN 尚未记录最新收尾状态。需要在 push 前修正这些模糊与遗漏，确保发布边界和验证证据长期可维护。

## What Changes

- 让 sdist 内容测试从全部成员推导唯一归档根目录，并显式断言所需根文件。
- 将 README 当前验证合同从 M22 历史合同测试中拆出，并同时约束章节唯一、格式有效和计数自洽。
- 更新 README 当前验证说明和 ACTION_PLAN 收尾台账，保留 M22 历史数字不变。
- 重新执行发布、文档和完整验证门禁，记录复审证据。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `golden-validation-core`: 加固发布物根目录推导与 README 当前验证章节唯一性合同，不改变产品运行时能力。

## Impact

影响 `tests/test_packaging.py`、`tests/test_collaboration_docs.py`、`README.md`、`ACTION_PLAN.md` 和验证记录；不新增依赖，不修改公共 API 或运行时行为。

## Why

M22 人类冒烟状态加载器通过比较 `ValueError` 文案区分文件过大与 JSON 解析失败，容易在重构或同文案 parser 异常时误分类；同时重复 plan ID 的测试使用空 ID，未真正覆盖唯一性分支。

## What Changes

- 在读取阶段直接返回稳定的文件过大错误，不再依赖异常字符串。
- 增加同文案 parser `ValueError` 回归，确保仍归类为 invalid JSON。
- 用两个合法重复 ID 精确覆盖唯一性失败，并收紧断言。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `triad-human-smoke`: 明确状态加载错误分类与重复合法 plan ID 的离线验收。

## Impact

仅影响 M22 人类冒烟脚本及其离线测试；不改变公开 CLI、真实模型流程、持久化 schema 或依赖。

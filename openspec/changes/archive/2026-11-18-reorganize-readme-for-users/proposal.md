# Proposal

## Why

用户要求 README 面向使用者，不展示开发里程碑与历史验收台账。现有测试反而强制 README 承载历史记录，需要随文档位置一起调整。

## What Changes

- 将里程碑、历史评估与开发验收入口迁往 docs/history，并修正相对链接。
- 保留产品使用、安全边界与当前验证入口，更新公开仓库克隆地址。
- 迁移历史文档契约并增加 README 不含里程碑编号的回归。

## Capabilities

无运行时或规格行为变更；纯文档与文档契约整理，skip_specs: true。

## Impact

README、文档索引、历史快照及相关离线文档测试；不修改 src 或依赖。保留正在进行的 GitHub CI 验收并在最终提交上复验。

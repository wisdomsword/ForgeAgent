## Why

项目除 `openai` 和 `prompt-toolkit` 外的直接运行时依赖，以及两个开发依赖，都只有下界而没有上界。重新解析环境时可跨越不兼容的主版本，导致同一提交无法稳定复现；当前依赖声明也与仓库已有的 `openai>=2.24,<3` 约束风格不一致。

## What Changes

- 为全部直接运行时依赖补充下一个不兼容主版本之前的上界。
- 为 `pytest` 与 `ruff` 开发依赖补充主版本上界。
- 重新生成 `uv.lock`，并同步依赖契约测试中的精确期望值。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `repository-lifecycle-integrity`：当前基线的直接依赖必须具有显式兼容上界，且锁文件不得发生无关版本漂移。

## Impact

- 配置：`pyproject.toml`。
- 锁文件：`uv.lock`。
- 测试：`tests/test_collaboration_docs.py`。
- 不升级已锁定版本，不新增依赖，不修改运行时源码。

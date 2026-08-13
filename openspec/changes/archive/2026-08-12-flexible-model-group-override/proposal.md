## Why

用户配置覆盖已有 provider group 时，`models` 总被合并追加，无法移除旧模型、清空组或安全地重新分组。添加到新组还会保留旧组成员，从而触发重复路由错误。

## What Changes

- 已存在 group 的用户覆盖只要显式提供 `models`，就替换完整模型列表。
- 省略 `models` 时继续继承内置列表并只覆盖其它标量。
- 空 `models: []` 是合法的显式清空。

## Capabilities

### Modified Capabilities

- `model-input-contracts`：provider group 的用户配置覆盖具有显式替换而非仅追加的模型列表语义。

## Impact

- 代码：`src/forgeagent/model_registry.py`。
- 测试：`tests/test_model_registry.py`。
- 迁移：过去依赖“显式 models 即追加”的配置需要将所有希望保留的模型完整列出。

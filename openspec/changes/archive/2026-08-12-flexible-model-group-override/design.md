## Decision

`_merge_config_data()` 保持 group 标量的浅覆盖。对已存在 group：

1. override 含 `models` key：直接使用该列表，包括空列表。
2. override 不含 `models` key：保留基础 group 的列表。

新 group 继续完整使用 override 值。该规则没有隐式追加，因此重新分组时用户可在旧组显式清空/替换并在新组显式列出模型。

## Compatibility

只改变用户显式提供 `models` 的现有 group 覆盖语义。没有 `models` 的覆盖不变；模型仍必须唯一属于一个 group。

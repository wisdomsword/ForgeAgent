## ADDED Requirements

### Requirement: 直接依赖具有可审计的兼容范围
ForgeAgent 的全部直接运行时依赖与开发依赖 MUST 同时声明最低版本和不兼容版本之前的上界。刷新锁文件时，若本次变更没有明确升级目标，已锁定包版本 MUST 保持不变。

#### Scenario: 当前依赖声明被重新解析
- **WHEN** 维护者对当前 `pyproject.toml` 执行锁文件一致性检查
- **THEN** 每个直接依赖均有显式上界
- **AND THEN** `uv.lock` 中除直接依赖 specifier 外不得出现无关版本漂移

#### Scenario: 准备跨越依赖上界
- **WHEN** 后续变更需要采用当前上界之外的版本
- **THEN** 该升级 MUST 先通过独立兼容性验证并显式修改依赖范围

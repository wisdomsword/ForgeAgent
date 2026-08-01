## Why

ForgeAgent 当前在每次请求中重复创建 provider SDK client，CLI 各入口的资源所有权和关闭责任不一致，模型数值参数允许非法值继续传播，且生命周期 verifier 使用依赖解释器版本的 AST 摘要。结果可能是连接池无法复用、资源泄漏、供应商收到非法请求，以及同一源码在 Python 3.11+ 矩阵中得到不同的 verifier 结果。

## What Changes

- 定义 `ModelClient`、provider SDK client、`Task` 与 CLI/evaluate/smoke 入口的明确所有权。
- 在一个 provider client 实例内复用普通请求和流式请求的 SDK client，并提供幂等关闭。
- 确保 CLI、evaluate、smoke、HTTP 和协作路径在成功、预检失败、提前返回、取消和异常时释放自己创建的资源；不关闭外部注入的 client。
- 在模型与 registry 边界拒绝零值、负值、非有限超时和非法能力上限。
- 将 verifier 摘要改为跨 Python 稳定的表示，同时继续检测受保护 verifier 源码变化。
- 增加生命周期、输入校验和 Python 版本回归测试，不新增运行时依赖。

## Capabilities

### New Capabilities

- `model-client-lifecycle`：provider client 复用、所有权、幂等关闭和入口清理契约。
- `model-input-contracts`：生成参数与模型能力的有限正数校验契约。

### Modified Capabilities

- `repository-lifecycle-integrity`：要求 verifier 摘要在支持的 Python 解释器之间稳定。
- `cli-boundary-maintainability`：在保持 CLI 行为的同时，使 client/Task 清理确定且可验证。

## Impact

- 影响代码：`client.py`、两个 provider client、`task.py`、`cli.py`、`_cli_parser.py`、`_cli_http.py`、`models.py`、`model_registry.py`。
- 影响测试：模型 client、模型 registry、CLI 生命周期和 repository lifecycle 测试，以及跨版本 verifier 探针。
- 对外行为：合法请求和现有 CLI 输出保持不变；非法数值更早以结构化校验错误失败。
- 依赖：不新增运行时或测试依赖，继续支持 Python `>=3.11`。

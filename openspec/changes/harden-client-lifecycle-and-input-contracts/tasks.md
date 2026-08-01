## 1. 建立生命周期契约和回归覆盖

- [ ] 1.1 增加 `ModelClient.close()`、Task 不拥有注入 client、provider SDK 复用、重复关闭和注入 transport 所有权的专项测试。
- [ ] 1.2 增加 CLI、smoke、evaluate、HTTP 和异常路径测试，断言本调用创建的 Task/client 恰好关闭一次，并保持既有输出和状态投影。

## 2. 实现 provider client 生命周期

- [ ] 2.1 增加幂等的 `ModelClient.close()` 契约和共享 provider 生命周期状态，不改变注入 transport 行为。
- [ ] 2.2 重构 OpenAI-compatible 普通/流式 transport，懒创建并共享一个 SDK client，且只关闭一次。
- [ ] 2.3 重构 Anthropic 普通/流式 transport，懒创建并共享一个 SDK client，保留 model-id 解析和错误分类。
- [ ] 2.4 验证 provider 请求、流式请求、失败路径和关闭后行为。

## 3. 在所有权入口清理资源

- [ ] 3.1 更新 `run_once`、smoke、evaluate、REPL、协作和 HTTP 路径，确保成功、提前返回、取消和异常时关闭本路径创建的 client 与 Task。
- [ ] 3.2 保持 `Task.close()` 只负责 Task 自有 backend 资源，并审计已有关闭顺序的回归。
- [ ] 3.3 运行 CLI、HTTP、协作和资源生命周期专项测试，保留受支持的 monkeypatch 接缝。

## 4. 加固模型输入契约

- [ ] 4.1 为生成参数、模型能力和 registry entry 增加有限正数约束。
- [ ] 4.2 将两个 provider request builder 的输出上限回退从 truthiness 改为显式 `None` 判断。
- [ ] 4.3 增加零值、负值、NaN、无穷、默认值、正值覆盖和 registry 错误投影测试。

## 5. 稳定生命周期 verifier 兼容性

- [ ] 5.1 将解释器相关的 AST dump 摘要替换为跨 Python 3.11+ 稳定的规范化源码片段摘要。
- [ ] 5.2 增加跨版本专项 verifier 测试/探针，并保留对受保护 verifier 源码缺失或修改的检测。

## 6. 全量验证和收尾

- [ ] 6.1 在 Python 3.11、3.12、3.14 下运行模型、CLI、HTTP、协作和 lifecycle 专项测试。
- [ ] 6.2 运行全量 pytest、Ruff check、Ruff format check、`uv build` 和 OpenSpec strict，且不增加 skip。
- [ ] 6.3 做最终两轮评审，检查所有权泄漏、公开行为漂移、非法值遗漏、secret/raw exception 泄漏和未列出的依赖，并记录 Comet verify 结果。

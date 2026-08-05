## Why

当前 ForgeAgent 固定系统提示要求模型先以原生 provider/model 身份回答。真实执行时，底层模型因此成为主要助手，而 ForgeAgent 退化为配置细节，这与 runtime-identity 契约以及 Agent 参考实现的产品优先角色组合相矛盾。

## What Changes

- 在固定系统提示中明确 ForgeAgent 是首要产品身份。
- 保持已批准 SOUL 对 ForgeAgent 产品身份内部的人格、名称、语气和价值观具有权威性。
- 固定提示不引导任何原生模型/provider 身份，避免模型把实现身份当成产品身份。
- 对明确的身份问句增加运行时输出边界：模型未以 ForgeAgent 开头时，由 ForgeAgent 返回可信的产品身份说明。
- 增加提示词措辞和身份优先级顺序的回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-identity`：明确 ForgeAgent 是首要产品身份，固定提示不引导其他助手或产品身份。

## Impact

只修改 runtime identity 提示资源、Task 身份输出边界、发布 smoke 的提示标记及专项测试；不涉及 API、schema、依赖、sandbox 或持久化。

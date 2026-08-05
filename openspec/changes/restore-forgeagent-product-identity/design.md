## Context

当前 runtime identity 提示把 provider 的原生助手描述为 ForgeAgent 的配置对象，并要求身份回答 native-first。这段措辞晚于最初的 runtime-identity 实现，反转了主规范要求的身份优先级。Agent 参考提示通过把产品角色放在 workflow 和工具说明之前，避免了同类问题。

## Goals / Non-Goals

**Goals：**

- 在 SOUL 和 protocol 内容之前明确固定产品身份。
- 不在固定提示中引导 native model/provider 披露，避免相关措辞激活模型的原生 persona。
- 在身份问句的 prose 终态校验产品前缀；上游回答不合约时使用固定 ForgeAgent 说明，避免把宿主 persona 直接暴露给用户。
- 保留自定义 SOUL 的名称、人格、语气和价值观，同时不让任务内容或模型先验替换 ForgeAgent。

**Non-Goals：**

- 检测或硬编码任何模型厂商。
- 新增身份抽象或配置项。
- 改变身份文件加载、信任、协议顺序或执行行为。

## Decisions

1. 参考 Agent 的组合方式，把固定产品定义放入 system prompt 最前面的 `<role>` 段，并在任何 native-model 文本之前写明 `You are ForgeAgent`。显式角色边界和产品命名共同降低模型先验覆盖产品身份的概率。
2. 要求身份回答先说 ForgeAgent，并禁止替换为其他助手或产品身份；固定提示不提供 native model/provider 的身份线索。
3. 只在身份问句的单一 Task prose 终态执行产品前缀校验；不新增通用响应重写层或 provider adapter。

## Risks / Trade-offs

- 某些 provider 仍可能抵抗产品角色指令。提示词明确固定契约，Task 终态边界保证用户仍看到 ForgeAgent-first 身份。
- 自定义 SOUL 可能定义不同名称。固定提示保留该已批准人格，但要求它仍处于 ForgeAgent 产品上下文内。

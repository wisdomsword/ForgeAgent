## Why

`main` 的 M47 基线仍通过 `_PROSE_NUDGE` 强制有效纯文本回答再调用一次模型；旧分支已经验证了直接以 `answered_in_prose` 结束且不冒充已执行完成的行为。M48 需要把该已验证行为独立移植到 M47，避免重复模型调用和终端正文重复显示。

## What Changes

- 从旧分支的 `2026-08-03-accept-direct-prose-answers` change 移植直接接受 prose 回答的行为，并按 M47 当前代码解决冲突。
- 有内容、无工具调用、无协议解析错误、无显式终态且无 required completion tool 的纯文本回答在同一轮以 `answered_in_prose` 结束。
- 保留纯文本回答“未执行验证”的状态和终端提示，不将其升级为 `completed`。
- 真实终端已经流式显示正文时，最终结果渲染不再重复打印正文。
- 保留空响应、截断响应、工具反馈、解析错误、显式非完成状态以及协作角色 required completion tool 的既有边界。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `completion-integrity`：允许单角色普通纯文本回答立即软完成，同时不削弱工具型响应和 required completion tool 的完成边界。

## Impact

- 基线：`main` 的 M47；旧分支仅作为已验证补丁与测试来源，不整体合并。
- 代码：`src/forgeagent/step.py` 的无反馈纯文本终止分支和 CLI 最终结果渲染。
- 测试：Step、Task、CLI、context 与 collaboration 的相关回归。
- 不新增依赖或配置，不修改协作角色的结构化提交语义。

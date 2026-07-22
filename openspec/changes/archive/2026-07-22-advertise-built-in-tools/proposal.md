## Why

ForgeAgent 的默认工具注册表已经包含 Survey、WebFetch、FileRead、FileWrite 和
FileList，但包内固定运行时协议只向模型说明 Exec 与 Edit，并要求执行型任务使用
Python/Exec。无自定义 identity 的真实模型因此无法可靠发现 FileWrite，即使用户
给出完整 ToolCall 标记也会连续以 prose 回答，阻断 M16 headless allowlist 的真实
黑盒验收。

## What Changes

- 使包内固定协议与默认工具注册表保持一致，列出每个内置工具的精确 ToolCall 参数。
- 明确直接工具匹配任务时优先使用对应工具，其余执行型任务再使用 Python/Exec。
- 增加固定提示词回归测试，确保无 identity 时仍向模型公开完整内置工具协议。
- 收窄 M16 人工黑盒的工具漂移判据：目标 FileWrite 已产生权威决策后，额外失败
  工具不覆盖该证据；额外成功工具或意外落盘仍判为不确定。
- 不改变工具注册、解析器、HTTP schema、allowlist、确认门或执行语义。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- runtime-identity：明确“完整固定协议”必须向模型公开默认注册的每个内置工具
  及其精确参数；这是既有要求的可测试化，不新增工具能力。

## Impact

- `src/forgeagent/res/prompts/protocol.md`
- `tests/test_identity.py`
- M16 FileWrite allowlist 真实模型黑盒验收
- `scripts/m16-filewrite-allowlist-blackbox.sh`
- `tests/test_m16_filewrite_allowlist_blackbox.py`
- 无新增依赖、配置、API 或 schema。

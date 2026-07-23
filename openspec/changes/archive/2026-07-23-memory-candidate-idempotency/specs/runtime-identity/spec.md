## MODIFIED Requirements

### Requirement: 分层运行时身份组合
系统 SHALL 按稳定的语义顺序组合固定 ForgeAgent harness 披露、中性默认或已批准 SOUL、不可覆盖协议、用户偏好、项目约束和手工记忆，并 SHALL 在组合完成后保留现有 MCP 工具描述。固定协议 MUST 向模型公开默认注册表中每个内置工具的协议名称、精确参数和适用场景；直接工具匹配目标时 SHALL 指示模型使用对应工具，其余执行型目标再使用 Python/Exec。固定协议 MUST 说明 `utils` 是执行代码中已注入且无需导入的对象，并 MUST 使用与 Runtime public API 一致的 `utils.set_state(key, value)` 和 `utils.get_state(key)` 调用签名；仅提交 Memory 候选的请求 MUST NOT 要求通过 Exec 记录同一偏好。身份文件内容 MUST 仅作为数据插入，不能选择模板、删除协议或改变协议顺序。协议不可覆盖保证仅限结构层面：系统保证身份文件内容不能修改、删除或移动固定协议字节的位置（Patch 6）；此保证不等于模型语义层的完整 prompt-injection 防护，模型仍可能响应身份文件中的指令性语义。组合所需包资源（system.j2、default_soul.md、protocol.md）缺失时，系统 MUST 报安装损坏，MUST NOT 静默回落为不含协议说明的提示词（Patch 5）。

#### Scenario: 全部可选身份层可用
- **WHEN** 用户 SOUL、USER 与已确认的项目 AGENTS、MEMORY 均存在
- **THEN** 系统按 harness 披露与 SOUL、固定协议、用户、项目、记忆的顺序向模型提供全部内容，并保留 MCP 工具描述

#### Scenario: 身份文件试图覆盖协议
- **WHEN** 任一身份文件包含要求忽略、替换或删除 ForgeAgent 协议的文本
- **THEN** 系统仍提供完整的程序控制协议段，且身份文件不能修改其内容或位置

#### Scenario: 无自定义身份时公开全部内置工具
- **WHEN** Task 使用包内默认身份与默认工具注册表运行
- **THEN** 固定协议说明 Exec、Edit、Survey、WebFetch、FileRead、FileWrite 和 FileList 的协议名称与精确参数，并指示模型在直接工具匹配目标时使用对应工具

#### Scenario: 固定协议公开准确运行时 API
- **WHEN** Task 向模型提供默认固定协议
- **THEN** 协议说明 `utils` 已注入且无需 import，使用 `set_state(key, value)` 位置参数签名，并说明纯记忆请求无需 Exec

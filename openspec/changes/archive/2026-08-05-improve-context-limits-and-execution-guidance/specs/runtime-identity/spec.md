## MODIFIED Requirements

### Requirement: 分层运行时身份组合
系统 SHALL 按稳定的语义顺序组合固定 ForgeAgent harness 披露、中性默认或已批准 SOUL、不可覆盖协议、用户偏好、项目约束和手工记忆，并 SHALL 在组合完成后保留现有 MCP 工具描述。固定协议 MUST 向模型公开默认注册表中每个内置工具的协议名称、精确参数和适用场景。模型缺少继续执行所必需的信息时 SHALL 使用 Survey；单个直接工具能够完成整个目标时 SHALL 优先使用该工具；递归遍历、跨文件聚合、内容哈希、转换或大量输出任务 SHALL 使用 Python/Exec。用户要求文件交付或结果过大时，协议 SHALL 指示执行代码把完整结果写入获准路径，并仅回复摘要、数量和位置。固定协议 MUST 说明 `utils` 是执行代码中已注入且无需导入的对象，并 MUST 使用与 Runtime public API 一致的 `utils.set_state(key, value)` 和 `utils.get_state(key)` 调用签名；仅提交 Memory 候选的请求 MUST NOT 要求通过 Exec 记录同一偏好。身份文件内容 MUST 仅作为数据插入，不能选择模板、删除协议或改变协议顺序。协议不可覆盖保证仅限结构层面：系统保证身份文件内容不能修改、删除或移动固定协议字节的位置（Patch 6）；此保证不等于模型语义层的完整 prompt-injection 防护，模型仍可能响应身份文件中的指令性语义。组合所需包资源（system.j2、default_soul.md、protocol.md）缺失时，系统 MUST 报安装损坏，MUST NOT 静默回落为不含协议说明的提示词（Patch 5）。

#### Scenario: 全部可选身份层可用
- **WHEN** 用户 SOUL、USER 与已确认的项目 AGENTS、MEMORY 均存在
- **THEN** 系统按 harness 披露与 SOUL、固定协议、用户、项目、记忆的顺序向模型提供全部内容，并保留 MCP 工具描述

#### Scenario: 身份文件试图覆盖协议
- **WHEN** 任一身份文件包含要求忽略、替换或删除 ForgeAgent 协议的文本
- **THEN** 系统仍提供完整的程序控制协议段，且身份文件不能修改其内容或位置

#### Scenario: 无自定义身份时公开全部内置工具
- **WHEN** Task 使用包内默认身份与默认工具注册表运行
- **THEN** 固定协议说明 Exec、Edit、Survey、WebFetch、FileRead、FileWrite 和 FileList 的协议名称与精确参数，并按完整目标而不是工具名称表面匹配选择直接工具或 Exec

#### Scenario: 缺少执行所需信息
- **WHEN** 执行型目标缺少范围、目标路径或其他继续执行所必需的信息
- **THEN** 固定协议指示模型调用 Survey，并在工具反馈返回后继续原 Task，而不是以 prose 结束后等待无上下文的新任务

#### Scenario: 递归聚合任务不使用单层 FileList 收尾
- **WHEN** 用户要求递归查找重复文件、计算内容哈希、统计数量并交付大量位置
- **THEN** 固定协议指示模型使用 Python/Exec 完成遍历、聚合和文件写入，不把一次 FileList 的截断片段作为完成结果

#### Scenario: 大结果以文件交付
- **WHEN** 用户要求把大量结果保存为文件或完整结果不适合人类终端阅读
- **THEN** 固定协议指示执行代码写入获准路径，最终回复只包含完成状态、关键数量、简要摘要和文件位置

#### Scenario: 固定协议公开准确运行时 API
- **WHEN** Task 向模型提供默认固定协议
- **THEN** 协议说明 `utils` 已注入且无需 import，使用 `set_state(key, value)` 位置参数签名，并说明纯记忆请求无需 Exec

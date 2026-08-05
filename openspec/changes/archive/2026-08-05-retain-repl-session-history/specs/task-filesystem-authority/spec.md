## MODIFIED Requirements

### Requirement: Restricted tasks can receive one task-scoped full-disk filesystem grant
ForgeAgent SHALL expose a typed `RequestFilesystemAccess` tool in the default task registry. In `restricted` tier, a successful interactive confirmation MUST expand Python execution and built-in file tools to the current platform filesystem root for the remainder of that Task while preserving the restricted subprocess, environment scrubbing, resource limits and network denial. The grant MUST NOT persist, cross into a later REPL input, be reconstructed from conversation history, or change the tier label to trusted.

#### Scenario: Restricted user approves full-disk access
- **WHEN** a restricted task requests full-disk filesystem access through `RequestFilesystemAccess` and the terminal user approves
- **THEN** subsequent Exec and built-in file calls in that Task can access paths outside the project root and the sandbox tier remains restricted

#### Scenario: Approved task does not prompt twice
- **WHEN** `RequestFilesystemAccess` is called again after the same Task already received the grant
- **THEN** ForgeAgent reports that full-disk filesystem access is already active without invoking the confirmer again

#### Scenario: Grant does not approve later side effects
- **WHEN** a restricted Task receives a full-disk filesystem grant and then calls FileWrite, WebFetch or MCP
- **THEN** each later side-effecting operation still follows its own confirmation or receipt policy and cannot reuse the filesystem grant as approval

#### Scenario: Grant expires with the task
- **WHEN** an approved restricted Task ends and the REPL starts a new task-producing input with inherited transcript
- **THEN** the new Task starts project-scoped and requires its own full-disk confirmation for project-external access

#### Scenario: 历史授权文本不恢复权限
- **WHEN** 新 Task 的模型上下文包含上一 Task 的授权批准文本或成功工具反馈
- **THEN** 新 Task 的 backend、Runtime 和内置文件工具仍从未授权状态开始，宿主不会把历史文本解释为当前授权

#### Scenario: User rejects full-disk access
- **WHEN** the terminal user rejects `RequestFilesystemAccess`
- **THEN** ForgeAgent returns structured denial feedback and leaves both the backend and built-in file tools project-scoped

#### Scenario: Rejected task does not prompt twice
- **WHEN** `RequestFilesystemAccess` is called again after the same Task already received a rejection
- **THEN** ForgeAgent returns the prior denied state without invoking the confirmer again

#### Scenario: No confirmation channel is available
- **WHEN** a restricted task requests full-disk access without an interactive confirmation channel
- **THEN** ForgeAgent records a denied task decision and rejects the request deterministically without changing filesystem authority or waiting for input

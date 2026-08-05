# task-filesystem-authority Specification

## Purpose
Define task-scoped filesystem authority independently from immutable project identity, including tier-specific elevation and audit boundaries.
## Requirements
### Requirement: Project identity root and task filesystem authority are independent
ForgeAgent MUST keep the resolved project root immutable for identity, memory and project semantics while maintaining a separate filesystem root for Python execution and built-in file tools. A filesystem authority change MUST NOT alter which project identity or project memory is loaded.

#### Scenario: Restricted task starts project-scoped
- **WHEN** a task starts with the default `restricted` tier
- **THEN** its Python execution and built-in file tools are limited to the resolved project root until an explicit task filesystem grant succeeds

#### Scenario: Filesystem grant does not change project identity
- **WHEN** a restricted task receives a full-disk filesystem grant
- **THEN** the already resolved project identity and project memory remain bound to the original project root

#### Scenario: Collaboration artifacts remain project-bound
- **WHEN** a collaboration role receives broader task filesystem authority
- **THEN** required candidate files, registered checks and candidate snapshot digests remain bound to the immutable project root

#### Scenario: Relative paths remain project-relative
- **WHEN** trusted mode or a restricted grant broadens the filesystem authority boundary to the platform root
- **THEN** relative built-in file-tool paths and generated WebFetch artifact paths still resolve from the immutable project root while absolute paths may use the broader authority

#### Scenario: Relative path escape remains blocked after authority broadens
- **WHEN** a relative file-tool or WebFetch artifact path contains `..` or resolves through a project symlink to an external target after full-disk access is active
- **THEN** ForgeAgent rejects the relative operation instead of applying the broader absolute-path authority

#### Scenario: Broader authority does not disclose host path structure
- **WHEN** trusted mode or a restricted grant lets a built-in file tool operate outside the project root
- **THEN** file-tool results and read audit records identify project files with project-relative paths and external files with basenames without exposing their absolute parent directories

### Requirement: Trusted tier has consistent host filesystem access
ForgeAgent MUST treat explicit `trusted` tier selection as authority for both Python Exec and built-in FileRead, FileWrite and FileList to access the current platform filesystem root, subject only to host operating-system permissions. Trusted filesystem access MUST NOT require an additional interactive prompt.

#### Scenario: Trusted Exec reads outside the project
- **WHEN** a trusted task executes Python that reads a host path outside the project root
- **THEN** ForgeAgent does not reject the read through its project-root sandbox boundary

#### Scenario: Trusted file tool reads outside the project
- **WHEN** a trusted task calls FileRead or FileList with a host path outside the project root
- **THEN** the built-in tool evaluates the path against the platform filesystem root and can complete without an additional approval

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

### Requirement: Container filesystem mounts do not expand at runtime
ForgeAgent MUST NOT expand a running `container` tier task from its configured project mount to the host filesystem root through `RequestFilesystemAccess`.

#### Scenario: Container task requests full-disk access
- **WHEN** a container task calls `RequestFilesystemAccess`
- **THEN** ForgeAgent returns a structured result explaining that runtime full-disk access is unavailable in container tier and does not invoke the confirmer or rebuild the container with a broader mount

### Requirement: Runtime authority facts are host-derived and explicit
ForgeAgent MUST include a host-generated Runtime Authority section in every Task system prompt stating the actual sandbox tier, resolved project root, initial filesystem scope, whether task-level full-disk access can be requested, and that MCP approval does not change ForgeAgent or MCP server filesystem authority. The model MUST be directed to use these facts instead of probing environment variables or MCP allowed-directory tools to infer its mode.

#### Scenario: Restricted prompt describes the upgrade path
- **WHEN** a restricted Task builds its system prompt
- **THEN** the prompt identifies restricted tier and project-scoped filesystem access and directs project-external work to `RequestFilesystemAccess`

#### Scenario: Trusted prompt states full-disk access
- **WHEN** a trusted Task builds its system prompt
- **THEN** the prompt identifies trusted tier and active host filesystem access without claiming restricted isolation

#### Scenario: Explicit built-in backend determines effective authority
- **WHEN** a caller supplies a built-in executor backend whose type conflicts with the requested tier label
- **THEN** ForgeAgent derives the effective tier, built-in file scope and Runtime Authority facts from the actual backend type rather than publishing contradictory permissions

#### Scenario: Explicit sandbox backend root conflicts with task root
- **WHEN** a caller supplies a built-in restricted or container backend whose allowed root differs from the Task project root
- **THEN** ForgeAgent rejects the contradictory configuration before running the Task

#### Scenario: Unknown custom backend authority is not guessed
- **WHEN** a caller supplies an executor backend whose permission semantics ForgeAgent cannot identify
- **THEN** ForgeAgent marks Exec authority as caller-defined, does not claim the built-in tier constrains Exec, and does not advertise dynamic filesystem elevation

#### Scenario: Explicit system prompt still receives authority facts
- **WHEN** a caller supplies a custom Task system prompt
- **THEN** ForgeAgent appends the same host-generated Runtime Authority section rather than omitting actual permission facts

#### Scenario: CLI single tasks carry audit identity
- **WHEN** a `run` or REPL single task makes a filesystem authority decision
- **THEN** the confirmation audit is emitted through the CLI audit sink with a non-empty task id

#### Scenario: Custom registry omits the access tool
- **WHEN** a restricted Task uses a custom tool registry that does not contain `RequestFilesystemAccess`
- **THEN** Runtime Authority reports dynamic filesystem access as unavailable rather than advertising an unusable tool

#### Scenario: MCP approval does not elevate ForgeAgent authority
- **WHEN** a user approves an MCP tool call, including an allowed-directory discovery call
- **THEN** the approval authorizes only that MCP call and does not change the Task backend, built-in file root or the MCP server's configured directories


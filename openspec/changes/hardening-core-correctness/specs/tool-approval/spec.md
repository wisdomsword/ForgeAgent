## ADDED Requirements

### Requirement: Restricted tools use one type-safe confirmation interface
ForgeAgent SHALL allow the CLI confirmer to describe and decide MCP, WebFetch and FileWrite requests without assuming that every request has MCP-specific fields.

#### Scenario: Confirming a WebFetch request
- **WHEN** the confirmer receives `WebFetchArgs`
- **THEN** it presents the request using WebFetch fields and does not raise an attribute or type error

#### Scenario: Confirming a FileWrite request
- **WHEN** the confirmer receives `FileWriteArgs`
- **THEN** it presents the target operation using FileWrite fields and does not raise an attribute or type error

#### Scenario: Confirming an MCP request
- **WHEN** the confirmer receives `MCPArgs`
- **THEN** it presents the server, tool and arguments using MCP fields

### Requirement: Terminal capability controls automatic confirmation
ForgeAgent SHALL attach the generic confirmer to restricted WebFetch, FileWrite and MCP operations independently of whether MCP servers are configured.

#### Scenario: Interactive terminal run
- **WHEN** a restricted tool is requested and the command has interactive TTY input and output
- **THEN** ForgeAgent asks the user to approve or reject the operation before execution

#### Scenario: REPL operation
- **WHEN** a restricted tool is requested from the REPL
- **THEN** ForgeAgent asks for confirmation before execution

#### Scenario: Non-interactive input
- **WHEN** WebFetch, FileWrite or an MCP call that still requires human confirmation is requested while stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation deterministically without waiting for input and identifies that no interactive confirmation channel is available

#### Scenario: Non-interactive auto-approved MCP call
- **WHEN** an MCP tool is listed in that server's `autoApprove` configuration and stdin or stdout is not a TTY
- **THEN** ForgeAgent treats the explicit configuration as pre-approval and executes without an interactive prompt

### Requirement: Confirmation prompts minimize sensitive exposure
ForgeAgent MUST redact structured secret-key values and known sensitive environment values from confirmation prompts, MUST NOT display FileWrite content, and MUST minimize disclosure of absolute file paths while retaining enough information for the user to identify the target.

#### Scenario: MCP arguments contain nested sensitive keys
- **WHEN** MCP arguments contain values under keys matching the existing secret-name policy at any nesting level
- **THEN** the confirmer replaces those values with a redaction marker and does not print the original values

#### Scenario: WebFetch URL contains credentials or sensitive query fields
- **WHEN** a WebFetch URL contains user information, known secret values or query keys matching the existing secret-name policy
- **THEN** the confirmer displays a sanitized URL without the sensitive values

#### Scenario: WebFetch hostname encodes a known secret
- **WHEN** a WebFetch hostname contains a percent-encoded or DNS case-normalized form of a known sensitive environment value
- **THEN** the confirmer decodes and matches the hostname using DNS case-insensitive semantics and does not display the sensitive value

#### Scenario: FileWrite uses an absolute path and sensitive content
- **WHEN** FileWrite requests an absolute path and arbitrary content
- **THEN** the confirmer displays a project-relative path when possible or a basename-only external path, displays only content length, and never displays the content

### Requirement: Restricted tool outcomes minimize sensitive exposure
ForgeAgent MUST prevent WebFetch failure outcomes and FileWrite success or failure outcomes from reintroducing raw URLs, hostnames, content or host absolute paths after confirmation.

#### Scenario: WebFetch is blocked by network policy
- **WHEN** a confirmed WebFetch request fails with `SSRFGuardError`
- **THEN** the tool returns the fixed detail `WebFetch blocked by network policy` without the original URL, hostname or exception text

#### Scenario: WebFetch fails at the network layer
- **WHEN** a confirmed WebFetch request fails with `OSError`
- **THEN** the tool returns the fixed detail `WebFetch request failed` without the original URL, hostname or exception text

#### Scenario: FileWrite succeeds with an absolute project path
- **WHEN** a confirmed FileWrite request resolves inside `allowed_root` and succeeds
- **THEN** the tool result identifies the target only by its project-relative path and does not include the model-provided absolute path or content

#### Scenario: FileWrite fails during the write operation
- **WHEN** a confirmed FileWrite request passes project-root validation but the filesystem write raises `OSError`
- **THEN** the tool returns the fixed detail `FileWrite failed` without the absolute path, content or exception text

### Requirement: Survey interaction remains separately controlled
ForgeAgent MUST keep `--interactive` scoped to Survey behavior and SHALL NOT require that flag for automatic TTY confirmation of WebFetch, FileWrite or MCP.

#### Scenario: TTY run without interactive flag
- **WHEN** a terminal user runs a task without `--interactive` and the task requests a restricted non-Survey tool
- **THEN** ForgeAgent still asks for tool confirmation while Survey remains disabled

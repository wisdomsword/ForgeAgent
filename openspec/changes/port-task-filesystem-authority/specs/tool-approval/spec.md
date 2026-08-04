## MODIFIED Requirements

### Requirement: Restricted tools use one type-safe confirmation interface
ForgeAgent SHALL allow the CLI confirmer to describe and decide MCP, WebFetch, FileWrite and task-level full-disk filesystem access requests without assuming that every request has MCP-specific fields.

#### Scenario: Confirming a WebFetch request
- **WHEN** the confirmer receives `WebFetchArgs`
- **THEN** it presents the request using WebFetch fields and does not raise an attribute or type error

#### Scenario: Confirming a FileWrite request
- **WHEN** the confirmer receives `FileWriteArgs`
- **THEN** it presents the target operation using FileWrite fields and does not raise an attribute or type error

#### Scenario: Confirming an MCP request
- **WHEN** the confirmer receives `MCPArgs`
- **THEN** it presents the server, tool and arguments using MCP fields

#### Scenario: Confirming a task filesystem request
- **WHEN** the confirmer receives `RequestFilesystemAccessArgs`
- **THEN** it states that approval grants read/write access to the full host filesystem for the current task and identifies the requested target without claiming that the sandbox tier becomes trusted

## ADDED Requirements

### Requirement: Full-disk confirmation is single-use, task-scoped and minimally disclosed
ForgeAgent MUST make at most one full-disk filesystem authority decision within one Task, MUST reuse that Task's approved or denied result without another prompt, MUST NOT persist or reuse the decision for another Task, and MUST record the initial decision through the existing confirmation audit interface. The confirmation and audit MUST NOT expose secrets or record the complete absolute requested path in audit parameters.

#### Scenario: Approved request is audited without absolute path
- **WHEN** a user approves a task filesystem request for an absolute path
- **THEN** ForgeAgent records an approved confirmation decision with fixed filesystem scope and tier fields without recording the complete path

#### Scenario: Rejected request is audited without authority change
- **WHEN** a user rejects a task filesystem request
- **THEN** ForgeAgent records the rejected decision, returns structured feedback and retains project-scoped authority

#### Scenario: Requested path contains unsafe display characters or a known secret
- **WHEN** a task filesystem request path contains control, formatting or known secret material
- **THEN** the confirmation renders a single-line escaped and secret-masked target and still reads exactly one approval answer

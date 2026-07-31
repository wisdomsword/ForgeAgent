# http-action-approvals Specification

## Purpose
TBD - created by archiving change bind-http-remote-action-approvals. Update Purpose after archive.
## Requirements
### Requirement: HTTP action approvals bind exact authority
ForgeAgent SHALL let an authenticated HTTP caller issue only short-lived `allow_once` approvals for an exact MCP action scope and canonical request digest. The host MUST bind every approval to exactly one newly accepted task before execution, and the model, goal, tool output, MCP server, or task options MUST NOT widen or transfer that authority.

#### Scenario: Exact approval is bound during task submission
- **WHEN** a caller issues an approval for one normalized MCP server/tool scope and request digest and submits its unique ID with a valid task
- **THEN** the host atomically binds the approval to the new server-owned task ID before scheduling the worker

#### Scenario: One approval in a submission is unavailable
- **WHEN** any supplied approval ID is unknown, duplicated, expired, revoked, consumed, or already bound
- **THEN** ForgeAgent rejects the entire submission without creating a task or partially binding any approval

#### Scenario: Model attempts to change approved authority
- **WHEN** an MCP call differs in task ID, action type, normalized scope, or canonical request digest
- **THEN** the approval does not match and ForgeAgent does not consume it or dispatch under it

### Requirement: Allow-once expiry and revocation are deterministic
Every HTTP action approval MUST have a bounded expiry and MUST authorize at most one dispatch. Expiry, revocation, and consumption MUST be serialized by the host; terminal approvals MUST NOT become active again.

#### Scenario: Matching approval is consumed once
- **WHEN** the bound task reaches an MCP dispatch whose exact scope and digest match an unexpired approval
- **THEN** ForgeAgent atomically marks the approval consumed before dispatch and refuses to use it for any later call

#### Scenario: Approval expires before consumption
- **WHEN** the approval deadline passes while the approval is issued or bound
- **THEN** ForgeAgent marks it expired and does not dispatch under it

#### Scenario: Revocation wins the race
- **WHEN** revocation acquires the approval state lock before a matching dispatch consumes the approval
- **THEN** the approval becomes revoked and the dispatch is denied

#### Scenario: Consumption wins the race
- **WHEN** a matching dispatch consumes the approval before revocation acquires the approval state lock
- **THEN** revocation reports the consumed terminal state and does not claim to undo the action

### Requirement: Approval state has a bounded safe projection
Approval APIs and audit events MUST expose only fixed, bounded metadata and MUST NOT expose bearer tokens, goals, prompts, raw tool arguments, evidence text, credentials, raw exceptions, or absolute host paths. The in-memory approval registry MUST be bounded and MUST fail closed at capacity.

#### Scenario: Caller queries an approval
- **WHEN** an authenticated caller queries a retained approval ID
- **THEN** ForgeAgent returns only its ID, action type, normalized scope, digest, mode, status, expiry and optional bound task ID

#### Scenario: Approval registry is at capacity
- **WHEN** no terminal record can be evicted and a caller tries to issue another approval
- **THEN** ForgeAgent returns a stable capacity error and creates no partial approval

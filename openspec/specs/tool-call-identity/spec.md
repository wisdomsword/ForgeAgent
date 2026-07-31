# tool-call-identity Specification

## Purpose
TBD - created by archiving change harden-loop-protocol-correctness. Update Purpose after archive.
## Requirements
### Requirement: Tool-call identities are unique across protocol channels
ForgeAgent SHALL merge text-protocol and native tool calls by stable call ID before dispatch. Identical duplicates MAY be retained once, but a call ID whose tool name or normalized arguments differ across channels MUST be marked as a protocol conflict and MUST NOT be dispatched.

#### Scenario: Identical dual-channel call
- **WHEN** text and native channels contain the same call ID, tool name, and equivalent arguments
- **THEN** the parser exposes one dispatchable call for that ID

#### Scenario: Conflicting dual-channel call
- **WHEN** text and native channels contain the same call ID with different tool names or arguments
- **THEN** the parser records a bounded conflict error and no call with that ID is dispatched

#### Scenario: Distinct calls remain independent
- **WHEN** channels contain different call IDs
- **THEN** each valid call remains dispatchable exactly once


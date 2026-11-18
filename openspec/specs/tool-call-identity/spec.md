# tool-call-identity Specification

## Purpose
Define stable tool-call identity, deduplication, and conflict handling across text and native channels so one logical call is dispatched at most once.

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

### Requirement: Invalid tool identity types remain recoverable
The parser MUST reject a non-string tool name as a structured parse error without raising an exception.

#### Scenario: Tool name is an array or object
- **WHEN** a text tool call supplies an array, object, boolean or null name
- **THEN** parsing returns an invalid-format error and the task can request correction

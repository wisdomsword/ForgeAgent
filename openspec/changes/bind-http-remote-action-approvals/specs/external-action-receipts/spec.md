## ADDED Requirements

### Requirement: Authenticated HTTP reconciliation preserves receipt authority
ForgeAgent SHALL permit its authenticated loopback HTTP control plane to read bounded open receipt projections and apply explicit reconciliation decisions through the authoritative receipt store. HTTP reconciliation MUST use the current receipt revision, MUST preserve receipt history, and MUST NOT dispatch, retry, resume, or fabricate delivery evidence.

#### Scenario: HTTP confirmation records external evidence only
- **WHEN** an authenticated caller confirms an open receipt with the current revision and bounded evidence
- **THEN** ForgeAgent updates only the receipt resolution/evidence and does not call the external server

#### Scenario: HTTP retry approval does not replay
- **WHEN** an authenticated caller marks an open receipt `retry_approved`
- **THEN** ForgeAgent closes the original receipt without dispatch and requires a separate future action with a new ID and valid authorization

#### Scenario: Process restarts after an unknown action
- **WHEN** a durable `unknown` receipt remains after restart while process-local action approvals have disappeared
- **THEN** the HTTP control plane can reconcile the receipt explicitly, but it cannot reconstruct or silently replay the expired approval

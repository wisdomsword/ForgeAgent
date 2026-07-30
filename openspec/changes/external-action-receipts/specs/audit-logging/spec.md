## ADDED Requirements

### Requirement: External receipt transitions are audited as projections
ForgeAgent SHALL emit one bounded, masked audit event for each external receipt creation, dispatch transition, confirmation, unknown result, or reconciliation decision. Audit records MUST reference the receipt/action identifier and stable status while omitting raw MCP arguments, credentials, full evidence text, and host paths. Audit failure MUST NOT make an unrecorded external dispatch appear safe to replay; the receipt store remains authoritative.

#### Scenario: Receipt transition is audited
- **WHEN** a receipt changes phase or receives a reconciliation decision
- **THEN** exactly one audit event records the action correlation, stable phase/decision, and safe target summary

#### Scenario: Audit sink is unavailable
- **WHEN** the audit sink rejects a receipt event
- **THEN** the authoritative receipt transition remains the source of truth, the audit sink is marked degraded using existing behavior, and no public response claims that the audit event was persisted

#### Scenario: Receipt audit data contains sensitive values
- **WHEN** a receipt target or evidence reference contains known secrets or unsafe control characters
- **THEN** the emitted audit JSONL contains masked, escaped, bounded values and no raw sensitive material

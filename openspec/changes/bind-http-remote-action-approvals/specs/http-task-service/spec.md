## ADDED Requirements

### Requirement: Authenticated HTTP callers manage one-time action approvals
The HTTP task service SHALL expose authenticated endpoints to issue, query, and revoke bounded `allow_once` MCP approvals and SHALL accept a bounded list of approval IDs during task submission. These routes MUST preserve the existing Bearer authentication, origin-form, body-size, no-store, loopback-only, and fixed-error boundaries.

#### Scenario: Valid approval lifecycle over HTTP
- **WHEN** an authenticated caller issues a valid exact approval, queries it, and revokes it before use
- **THEN** the service returns deterministic safe projections and the revoked approval cannot authorize a task action

#### Scenario: Task claims approvals
- **WHEN** an authenticated task submission includes a valid bounded list of issued approval IDs
- **THEN** the service binds all of them to the created task before worker publication and does not pass those IDs to the model or ordinary task options

#### Scenario: Approval fields appear in an unsupported location
- **WHEN** a client places approval scope, digest, expiry, or authority fields in goal text, ordinary options, Loop resume fields, or any schema location other than the documented approval endpoints and approval ID list
- **THEN** the service rejects or ignores them as data and grants no authority

#### Scenario: Listener configuration attempts remote exposure
- **WHEN** action approval endpoints are enabled while the configured bind address is not loopback
- **THEN** service startup still fails closed and exposes no listener

### Requirement: HTTP receipt recovery is explicit and task-scoped
The HTTP task service SHALL let an authenticated caller list open external-action receipts for one retained task and apply an explicit compare-and-swap reconciliation decision. After process restart removes task records, an exact task ID match on a durable open receipt SHALL establish only that receipt recovery scope. It MUST NOT expose receipts owned by another task, raw arguments, or an automatic replay operation.

#### Scenario: List one task's pending receipts
- **WHEN** an authenticated caller lists receipts for a retained task
- **THEN** the service returns only bounded public fields for open receipts whose authoritative task ID matches the route

#### Scenario: Recover durable receipt after process restart
- **WHEN** the process-local task record and approvals are gone but a durable open receipt exactly matches the route task ID
- **THEN** the service permits listing and reconciliation for that receipt only, without reconstructing an approval or task and without dispatching

#### Scenario: Resolve an unknown receipt with evidence
- **WHEN** an authenticated caller supplies the current revision, the `confirmed` decision, and bounded evidence for an unknown receipt owned by the task
- **THEN** the service records the resolution and returns the updated safe projection without invoking MCP

#### Scenario: Abandon or permit a new attempt
- **WHEN** an authenticated caller chooses `abandoned` or `retry_approved` for an open task-owned receipt at its current revision
- **THEN** the service records that decision without dispatch, and any future attempt requires a new action ID and independent authorization

#### Scenario: Receipt does not match route authority
- **WHEN** the action ID is unknown, belongs to a different task, is already resolved, or has a stale revision
- **THEN** the service returns a fixed non-disclosing not-found or conflict error and performs no transition

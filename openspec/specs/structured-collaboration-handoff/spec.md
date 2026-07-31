# structured-collaboration-handoff Specification

## Purpose
Define host-owned, bounded, digest-bound collaboration handoff packets and audit projections that preserve authority and recovery boundaries across roles.
## Requirements
### Requirement: Collaboration roles exchange a bounded structured handoff

ForgeAgent SHALL create a validated `HandoffPacket` for each Planner, Generator and Evaluator boundary. The packet MUST contain bounded goal/scope projection, verified facts, explicit assumptions, open side-effect receipt projection, capability/approval projection, checkpoint, stop conditions, and a fixed return owner. Model-generated free-form summaries MUST NOT become durable handoff facts.

#### Scenario: Generator receives Planner handoff
- **WHEN** a Triad plan is submitted and confirmed
- **THEN** the Generator task data contains a validated handoff with the frozen plan digest, current phase, verified facts, explicit empty-or-bounded assumptions, capability/approval projection and return owner `evaluator`

#### Scenario: Evaluator receives Generator handoff
- **WHEN** the Generator successfully submits the current Candidate
- **THEN** the Evaluator task data contains a handoff tied to the current generator attempt and revision, lists only its read-only capabilities/frozen checks, and returns responsibility to `caller`

#### Scenario: Rejected Candidate returns to Generator
- **WHEN** Evaluator submits a failing verdict and the runner starts a new Generator attempt
- **THEN** the handoff preserves the frozen plan digest, includes bounded failed evaluation facts, identifies the current attempt and revision, and returns responsibility to `evaluator`

### Requirement: Handoff packets are deterministic and resumable

ForgeAgent SHALL derive handoff packets only from validated collaboration state and host-owned public projections. The same state, role, attempt and capability inputs MUST produce the same packet and digest. Resume MUST rebuild the packet from durable state rather than trusting an old model summary. Handoff persistence MUST NOT change existing collaboration state transition or completion invariants.

The raw collaboration goal used to execute Planner, Generator and Evaluator tasks MUST remain an internal execution input and MAY retain a legitimate absolute path required by the task. `HandoffPacket.goal`, CollaborationReport and handoff audit MUST use a separate bounded public projection that masks secrets, absolute paths and unsafe characters. Public audit MUST NOT contain either the raw goal or the public goal prose.

#### Scenario: Resume reconstructs the same handoff
- **WHEN** a collaboration resumes from an evaluator phase with an empty verdict
- **THEN** the new Evaluator receives the same handoff digest for the same state and host capability projection, and no in-memory pre-crash summary is required

#### Scenario: Handoff input contains unsafe text
- **WHEN** goal, evidence, receipt labels or loop context contain secrets, absolute paths or control characters
- **THEN** the packet's public fields use existing masking and bounded text rules, while internal role task data preserves only the validated execution goal and routing or receipt ownership retains raw internal identities only where already required

#### Scenario: Legitimate execution path remains available
- **WHEN** a validated goal instructs a role to process an absolute path such as `/data/input.csv`
- **THEN** the internal role task goal retains that path for execution, while `HandoffPacket.goal`, CollaborationReport and audit contain no absolute path or raw goal body

### Requirement: Handoff exposes risk and authority without granting authority

ForgeAgent SHALL project open receipts using only public server/tool labels, phase and dispatch certainty, and SHALL mark unresolved actions as requiring explicit reconciliation. Capability and approval fields MUST be host-derived summaries; the packet MUST NOT grant new tools, bypass confirmation, resolve receipts, replay actions, or alter role ownership.

#### Scenario: Open external receipt is present
- **WHEN** a role boundary has an open external-action receipt
- **THEN** the handoff reports a bounded unresolved receipt projection and requires explicit reconciliation before retry; it does not call `resolve()` or replay the action

#### Scenario: No receipt store is available
- **WHEN** a role runs without a receipt store
- **THEN** the handoff explicitly reports that receipt visibility is unavailable rather than claiming there are no external actions

### Requirement: Handoff audit is bounded and compatible

ForgeAgent SHALL emit a handoff audit event containing only role, phase, attempt, revision, digest prefix, bounded counts, and return owner. Existing `CollaborationReport` fields, Single mode behavior, role Submit gates, loop context compatibility, and CLI/HTTP public report shape MUST remain unchanged.

#### Scenario: Handoff audit is emitted
- **WHEN** a role task starts with a handoff packet
- **THEN** audit contains a stable digest prefix and counts but no goal prose, plan text, file content, command, secret, absolute path or full receipt identifier

#### Scenario: Single mode remains unchanged
- **WHEN** a task uses Single mode
- **THEN** no collaboration handoff is created and the existing `TaskOutcome` path is used

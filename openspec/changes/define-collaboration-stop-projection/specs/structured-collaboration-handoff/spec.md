## MODIFIED Requirements

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

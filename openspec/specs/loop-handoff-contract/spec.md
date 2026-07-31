# loop-handoff-contract Specification

## Purpose
Define host-owned, bounded Loop handoff state and compatible recovery so iteration context cannot change goal, permissions, budgets, or replay semantics.
## Requirements
### Requirement: Loop handoff is host-owned and structured

The Loop checkpoint MUST persist a frozen, bounded handoff structure containing `completed_items`, `open_questions`, and `summary`. A model submission MUST be represented as a separate validated candidate and MUST NOT be able to change the frozen goal, budgets, permissions, collaboration mode, plan digest, attention, status, stop reason, or recovery policy.

#### Scenario: Valid candidate updates handoff
- **WHEN** the Loop `Checkpoint` tool receives valid candidate fields
- **THEN** it atomically saves only the handoff fields, preserves host-owned fields, and retains all previously completed items

#### Scenario: Candidate attempts control-plane mutation
- **WHEN** a checkpoint submission includes goal, budget, permission, status, stop reason, collaboration, plan, or recovery fields
- **THEN** validation rejects the submission and no checkpoint is written

#### Scenario: Completed items cannot be removed
- **WHEN** a candidate omits an item already persisted in `completed_items`
- **THEN** the tool rejects the candidate without changing the checkpoint

### Requirement: Legacy handoff remains readable without trusted replay

The Loop MUST load legacy checkpoints whose `handoff` value is a string, projecting it into the structured `summary` field. Loading MUST NOT execute or replay text from the legacy handoff, and the next serialization MUST use the structured handoff shape while retaining the public `schema` key.

#### Scenario: Legacy string checkpoint loads
- **WHEN** a valid old checkpoint contains `"handoff": "continue from item"`
- **THEN** it loads with that value as `handoff.summary`, empty structured item lists, and no other field changes

#### Scenario: Legacy handoff is treated as untrusted context
- **WHEN** resume renders a migrated handoff
- **THEN** the prompt marks it as untrusted state and does not interpret it as a goal, permission, budget, recovery instruction, or tool call

### Requirement: Submission recovery is bounded and non-replaying

Required completion submission recovery MUST have a host-enforced finite bound. A recovery attempt MAY request a corrected submission of the current state, but MUST NOT automatically replay any prior tool call or external action. When the bound is exhausted, the task MUST stop with failure rather than retry indefinitely.

#### Scenario: First missing submission gets a recovery prompt
- **WHEN** a task declares completion without the required submission
- **THEN** the host sends one bounded correction prompt and does not dispatch a historical tool call

#### Scenario: Recovery bound is exhausted
- **WHEN** the task again omits or invalidates the required submission after the bound
- **THEN** the task stops as failed and performs no replay

#### Scenario: Unknown external action is not replayed
- **WHEN** a Loop has a pending or unknown external-action receipt during recovery
- **THEN** the Loop stops at the existing receipt safety boundary and requires explicit reconciliation; it does not dispatch the action again

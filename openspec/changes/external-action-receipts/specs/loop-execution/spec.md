## ADDED Requirements

### Requirement: Loop execution gates on unresolved external actions
Before starting a new Loop iteration and before executing a resumed Loop, ForgeAgent MUST query the authoritative receipt store for unresolved receipts belonging to that Loop. If any receipt is unresolved, the Loop MUST stop with a stable `external_action_pending` reason and MUST NOT invoke a model, tool, collaboration role, or automatic retry.

#### Scenario: Resume with an unresolved receipt
- **WHEN** a valid Loop checkpoint is resumed while one of its receipts is `prepared`, `dispatched`, or `unknown` without reconciliation
- **THEN** ForgeAgent returns a bounded stopped report with `external_action_pending` before creating a Task

#### Scenario: Iteration leaves an unresolved receipt
- **WHEN** a running Loop iteration produces an unresolved external action
- **THEN** the Loop persists its normal accounting, then stops at the next safe boundary with `external_action_pending` and does not start another iteration

#### Scenario: Reconciled receipt permits continuation
- **WHEN** all receipts for a Loop are confirmed, abandoned, or explicitly resolved for a new attempt
- **THEN** Loop resume may continue, but no original action is replayed automatically and any new action uses a new identifier

## ADDED Requirements

### Requirement: Collaboration lifecycle events are attributable and minimally disclosing
The collaboration path MUST emit audit events for mode routing, role start/outcome, plan submission/confirmation, evaluation verdict, rejection and terminal stop. Events MUST carry task/Loop correlation, stable mode/role/phase/model identifiers and bounded counters while omitting the goal, plan text, evaluation feedback text, prompts, tool arguments, artifact contents, credentials and absolute paths.

#### Scenario: Role lifecycle is audited
- **WHEN** Planner, Generator or Evaluator starts and reaches an outcome
- **THEN** events record role, mode, attempt, model identifier, stable status, duration and normalized usage without conversation content

#### Scenario: Plan confirmation is audited
- **WHEN** an interactive user or headless policy approves, denies or cannot confirm a Planner plan
- **THEN** one event records the decision, plan item count and digest prefix without plan text or goal

#### Scenario: Evaluation rejection is audited
- **WHEN** Evaluator rejects one or more acceptance items
- **THEN** one event records pass/fail counts, rejection number and bounded reason enums without actual/expected text or file contents

#### Scenario: Collaboration stops
- **WHEN** collaboration completes, exhausts rejection attempts, fails, needs confirmation or is cancelled
- **THEN** one event records mode, terminal reason and cumulative counters, and serialization failure follows existing audit-degraded behavior


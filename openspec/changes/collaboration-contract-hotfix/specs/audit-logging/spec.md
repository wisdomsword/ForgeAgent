## MODIFIED Requirements

### Requirement: Collaboration lifecycle events are attributable and minimally disclosing
The collaboration path MUST emit `collaboration.route`, `collaboration.role.start`, `collaboration.role.outcome`, plan submission/confirmation, evaluation verdict, rejection and terminal stop audit events. Events MUST carry task/Loop correlation, stable mode/role/phase/model identifiers and bounded counters while omitting the goal, plan text, evaluation feedback text, prompts, tool arguments, artifact contents, credentials and absolute paths. Role construction or execution failure MUST still emit a stable outcome without exception text.

#### Scenario: Mode routing is audited
- **WHEN** an entry point resolves a single, Duo or Triad mode
- **THEN** one route event records the selected mode, stable reason, requested mode or default marker, and override flag without the task goal

#### Scenario: Role lifecycle is audited
- **WHEN** Planner, Generator or Evaluator starts and reaches an outcome
- **THEN** start/outcome events record role, mode, phase, attempt, model identifier, tier, stable status, duration and normalized usage without conversation content

#### Scenario: Role construction or execution fails
- **WHEN** a role builder, role Task or resource close raises
- **THEN** an outcome event records a stable configuration, role-error or interrupted status with unavailable zero usage and no exception text

#### Scenario: Plan confirmation is audited
- **WHEN** an interactive user or headless policy approves, denies or cannot confirm a Planner plan
- **THEN** one event records the decision, plan item count and digest prefix without plan text or goal

#### Scenario: Evaluation rejection is audited
- **WHEN** Evaluator rejects one or more acceptance items
- **THEN** one event records pass/fail counts, rejection number and bounded reason enums without actual/expected text or file contents

#### Scenario: Collaboration stops
- **WHEN** collaboration completes, exhausts rejection attempts, fails, needs confirmation or is cancelled
- **THEN** one event records mode, terminal reason and cumulative counters, and serialization failure follows existing audit-degraded behavior

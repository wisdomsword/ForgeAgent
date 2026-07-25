## MODIFIED Requirements

### Requirement: Cancellation has bounded terminal semantics

The service MUST expose authenticated cancellation for accepted ordinary tasks, Loops, and collaborations; cancellation MUST prevent future task rounds, Loop iterations, or collaboration role sessions when possible, produce a distinct `cancelled` terminal state, persist a Loop cancellation checkpoint when applicable, and MUST NOT affect other tasks. The cancellation race with completion or failure MUST have deterministic precedence: a terminal Loop or collaboration report produced by the worker MUST NOT be overwritten by a cancel signal that arrives after the report reached a terminal status.

#### Scenario: Cancel before execution
- **WHEN** a client cancels a queued ordinary task or Loop before its worker begins execution
- **THEN** the task transitions to cancelled without invoking the model or tools and a Loop records cancellation before returning if its checkpoint was created

#### Scenario: Cancel during execution
- **WHEN** a client cancels a running ordinary task or Loop
- **THEN** the service requests cooperative stop at the next safe round, tool, or iteration boundary, returns a bounded acknowledgement, and eventually reports deterministic terminal cancellation

#### Scenario: Cancel an already terminal task
- **WHEN** a client cancels a task or Loop that is already terminal
- **THEN** the service leaves the terminal result and checkpoint unchanged and returns an idempotent acknowledgement

#### Scenario: Late cancel does not overwrite a terminal collaboration report
- **WHEN** a Duo/Triad worker returns a terminal collaboration report (such as `completed`) and the record's cancel signal is set afterwards but before the service records the result — for example during service shutdown or a late cancel call racing resource close
- **THEN** the service records the terminal collaboration report's status and reason unchanged and does not replace them with `cancelled`

#### Scenario: Cooperatively cancelled collaboration remains cancelled
- **WHEN** a Duo/Triad worker itself stops cooperatively and returns a collaboration report with status `cancelled`
- **THEN** the service records the task as `cancelled`

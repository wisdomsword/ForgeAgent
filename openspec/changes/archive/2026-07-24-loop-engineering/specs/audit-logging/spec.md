## ADDED Requirements

### Requirement: Loop lifecycle events are attributable and minimally disclosing
The core Loop path MUST emit audit events for Loop start/resume, successful checkpoint persistence, iteration outcome, and terminal stop. Events MUST carry the Loop/task correlation and bounded counters while omitting the goal, checkpoint body, handoff text, completed/pending item text, absolute checkpoint path, prompts, credentials, and raw failure detail.

#### Scenario: Loop starts or resumes
- **WHEN** a CLI or HTTP request starts or resumes a Loop
- **THEN** one lifecycle event records the public trigger kind, Loop identifier, safe budget presence/limits, and `started` or `resumed` result without goal or checkpoint content

#### Scenario: Checkpoint persists
- **WHEN** a model checkpoint or automatic iteration checkpoint is atomically committed
- **THEN** one event records Loop/task correlation, schema version, iteration and aggregate item counts, and success without item text or host path

#### Scenario: Loop iteration ends
- **WHEN** an underlying Task iteration completes or fails
- **THEN** one event records the stable Task reason and cumulative round/token/failure counters without raw model response or failure text

#### Scenario: Loop reaches terminal state
- **WHEN** a Loop completes, is cancelled, reaches a budget, or encounters an unrecoverable checkpoint/configuration failure
- **THEN** one event records the stable terminal and stop reason plus bounded counters, and serialization failure follows the existing audit-degraded behavior

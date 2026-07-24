## ADDED Requirements

### Requirement: REPL exposes explicit Duo and Triad commands
The REPL command table SHALL include `/duo <goal>` and `/triad <goal>` using the same completion, help, history and input compatibility paths as existing slash commands. Missing goals MUST produce bounded usage guidance without starting a task.

#### Scenario: Duo slash command
- **WHEN** a user submits `/duo verify this report`
- **THEN** the REPL removes the command prefix and runs the remaining goal in Duo mode

#### Scenario: Triad slash command
- **WHEN** a user submits `/triad implement the parser`
- **THEN** the REPL removes the command prefix and runs the remaining goal in Triad mode, including Planner confirmation

#### Scenario: Slash candidates and help
- **WHEN** a user types `/d`, `/t`, or requests `/help duo`
- **THEN** candidates and help are derived from the shared command table and describe the collaboration cost and semantics


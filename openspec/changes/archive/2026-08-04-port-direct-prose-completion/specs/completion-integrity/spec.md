## ADDED Requirements

### Requirement: Direct prose answers terminate without protocol recovery
In a single-role task without a required completion tool, ForgeAgent SHALL terminate a non-empty response that has no tool calls, no protocol parse errors and no explicit terminal status as `answered_in_prose` in that same round. ForgeAgent MUST preserve this as an unverified soft completion and MUST NOT report it as execution-verified `completed`.

#### Scenario: Informational answer completes in one round
- **WHEN** a model returns a non-empty plain-text answer with no tool calls, parse errors or explicit terminal status
- **THEN** ForgeAgent makes no recovery model call and terminates that round as `answered_in_prose`

#### Scenario: Streamed informational answer is displayed once
- **WHEN** a terminal streams a direct plain-text answer before rendering its final task outcome
- **THEN** ForgeAgent retains one copy of the answer and does not print the same round body again

#### Scenario: Required completion tool still takes precedence
- **WHEN** a role configured with a required completion tool returns plain text without successfully calling that tool
- **THEN** ForgeAgent does not accept the prose as a soft completion and applies the existing bounded submission recovery behavior

#### Scenario: Tool or parse feedback still continues
- **WHEN** a response contains tool activity or protocol parse errors
- **THEN** ForgeAgent processes and feeds back those results instead of terminating that response as `answered_in_prose`
